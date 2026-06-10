#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
RUN_DIR="$ROOT_DIR/.run"

mkdir -p "$RUN_DIR"

# --- 杀进程树：先杀子进程，再杀父进程 ---
kill_tree() {
  local pid="$1"
  # 递归杀所有子进程
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

# --- 清理旧进程 ---
cleanup_old() {
  local pid_file="$1" name="$2"
  if [ -f "$pid_file" ]; then
    local old_pid
    old_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
      echo "停止旧 $name (PID $old_pid)..."
      kill_tree "$old_pid"
      sleep 1
      # 确保已退出
      if kill -0 "$old_pid" 2>/dev/null; then
        kill -9 "$old_pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pid_file"
  fi
}

# --- 等待 HTTP 健康检查（GET）---
wait_http_ok() {
  local name="$1" url="$2" timeout_s="$3"
  local start_ts now elapsed
  start_ts="$(date +%s)"
  while true; do
    if curl --noproxy '*' -fsS -m 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if [ "$elapsed" -ge "$timeout_s" ]; then
      echo "$name 健康检查失败: $url 超时 ${timeout_s}s"
      return 1
    fi
    sleep 0.5
  done
}

# --- 等待 POST 健康检查（后端 /health）---
wait_http_post_ok() {
  local name="$1" url="$2" timeout_s="$3"
  local start_ts now elapsed
  start_ts="$(date +%s)"
  while true; do
    if curl --noproxy '*' -fsS -m 2 -X POST -H "Content-Type: application/json" -d '{}' "$url" >/dev/null 2>&1; then
      return 0
    fi
    now="$(date +%s)"
    elapsed=$((now - start_ts))
    if [ "$elapsed" -ge "$timeout_s" ]; then
      echo "$name 健康检查失败: $url 超时 ${timeout_s}s"
      return 1
    fi
    sleep 0.5
  done
}

# --- 检查 PID 是否存活 ---
pid_alive() {
  local pid_file="$1"
  [ -f "$pid_file" ] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

# --- 查询占用端口的 PID（不依赖 ss） ---
find_port_pids() {
  local port="$1"
  local pids=""

  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -t -iTCP:${port} -sTCP:LISTEN 2>/dev/null | sort -u || true)"
  fi

  if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
    pids="$(fuser ${port}/tcp 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true)"
  fi

  echo "$pids"
}

# --- 读取数据库配置 ---
read_db_config() {
  local cfg="$ROOT_DIR/config.json"
  if [ ! -f "$cfg" ]; then
    echo "缺少配置文件: $cfg"
    return 1
  fi
  mapfile -t _db_lines < <(python3 -c '
import json
from pathlib import Path
cfg = json.loads(Path("'"$cfg"'").read_text(encoding="utf-8"))
db = cfg.get("database", {})
print(db.get("host", "127.0.0.1"))
print(db.get("port", 5432))
print(db.get("user", "postgres"))
print(db.get("password", ""))
print(db.get("db_name", "postgres"))
')
  DB_HOST="${_db_lines[0]}"
  DB_PORT="${_db_lines[1]}"
  DB_USER="${_db_lines[2]}"
  DB_PASSWORD="${_db_lines[3]}"
  DB_NAME="${_db_lines[4]}"
}

# --- 读取端口配置 ---
read_port_config() {
  local cfg="$ROOT_DIR/config.json"
  if [ ! -f "$cfg" ]; then
    echo "缺少配置文件: $cfg"
    return 1
  fi
  DEV_PORT="$(python3 -c '
import json
from pathlib import Path
cfg = json.loads(Path("'"$cfg"'").read_text(encoding="utf-8"))
print(cfg["app"]["dev_port"])
')"
}

# --- 数据库预检查 ---
precheck_database() {
  read_db_config || return 1

  if ! command -v pg_isready >/dev/null 2>&1; then
    echo "警告: 未找到 pg_isready，跳过数据库连通性预检。"
    return 0
  fi

  if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
    echo "数据库未就绪: $DB_HOST:$DB_PORT"
    echo "请先启动 PostgreSQL，再执行 ./scripts/start_dev.sh"
    return 1
  fi

  if command -v psql >/dev/null 2>&1; then
    if ! PGPASSWORD="$DB_PASSWORD" psql \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
      -c "select 1;" >/dev/null 2>&1; then
      echo "数据库认证失败: user=$DB_USER host=$DB_HOST port=$DB_PORT"
      echo "请检查 config.json 中 database.user / database.password"
      return 1
    fi

    if ! PGPASSWORD="$DB_PASSWORD" psql \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
      -tAc "select 1 from pg_database where datname='${DB_NAME}'" | grep -q 1; then
      echo "提示: 数据库 $DB_NAME 不存在。后端启动时会尝试自动创建。"
    fi
  fi

  return 0
}

cleanup_old "$RUN_DIR/backend-dev.pid" "backend"
cleanup_old "$RUN_DIR/frontend-dev.pid" "frontend"

read_port_config

# 额外清理残留端口占用
for port in 9000 "$DEV_PORT"; do
  pids_on_port="$(find_port_pids "$port")"
  for pid_on_port in $pids_on_port; do
    if [ -n "$pid_on_port" ]; then
      echo "清理端口 $port 上的残留进程 (PID $pid_on_port)..."
      kill_tree "$pid_on_port"
      sleep 0.5
    fi
  done
done

if ! precheck_database; then
  exit 1
fi

# --- 启动后端 ---
cd "$BACKEND_DIR"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy ftp_proxy FTP_PROXY
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt 2>&1 | tail -3

start_backend() {
  nohup uvicorn app.main:app --host 0.0.0.0 --port "$DEV_PORT" > "$RUN_DIR/backend-dev.log" 2>&1 &
  echo $! > "$RUN_DIR/backend-dev.pid"
}

start_backend
sleep 0.5
if ! pid_alive "$RUN_DIR/backend-dev.pid" || ! wait_http_post_ok "backend" "http://127.0.0.1:$DEV_PORT/health" 20; then
  echo "backend 首次启动失败，尝试重启一次..."
  if pid_alive "$RUN_DIR/backend-dev.pid"; then
    kill_tree "$(cat "$RUN_DIR/backend-dev.pid")"
    sleep 1
  fi
  start_backend
  sleep 0.5
  if ! pid_alive "$RUN_DIR/backend-dev.pid" || ! wait_http_post_ok "backend" "http://127.0.0.1:$DEV_PORT/health" 20; then
    echo "backend 启动失败，最近日志："
    tail -n 120 "$RUN_DIR/backend-dev.log" || true
    deactivate
    exit 1
  fi
fi
deactivate

# --- 启动前端 ---
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install 2>&1 | tail -3
fi
nohup npm run dev > "$RUN_DIR/frontend-dev.log" 2>&1 &
echo $! > "$RUN_DIR/frontend-dev.pid"
sleep 0.5
if ! pid_alive "$RUN_DIR/frontend-dev.pid" || ! wait_http_ok "frontend" "http://127.0.0.1:9000/" 25; then
  echo "frontend 启动失败，最近日志："
  tail -n 120 "$RUN_DIR/frontend-dev.log" || true
  exit 1
fi

echo "dev started: frontend=9000 backend=$DEV_PORT"
