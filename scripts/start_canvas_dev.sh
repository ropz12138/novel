#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

# --- 杀进程树 ---
kill_tree() {
  local pid="$1"
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
    fi
    rm -f "$pid_file"
  fi
}

# --- 等待 HTTP 健康检查 ---
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

# --- 检查 PID 是否存活 ---
pid_alive() {
  local pid_file="$1"
  [ -f "$pid_file" ] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

# --- 查询占用端口的 PID ---
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

# --- 读取端口配置 ---
read_config() {
  local cfg="$ROOT_DIR/config.json"
  if [ ! -f "$cfg" ]; then
    echo "缺少配置文件: $cfg"
    return 1
  fi
  mapfile -t _cfg_lines < <(python3 -c '
import json
from pathlib import Path
cfg = json.loads(Path("'"$cfg"'").read_text(encoding="utf-8"))
print(cfg["app"]["dev_port"])
print(cfg["frontend"]["dev_port"])
')
  BACKEND_PORT="${_cfg_lines[0]}"
  FRONTEND_PORT="${_cfg_lines[1]}"
}

cleanup_old "$LOG_DIR/canvas-backend-dev.pid" "canvas-backend"
cleanup_old "$LOG_DIR/canvas-frontend-dev.pid" "canvas-frontend"

read_config

# 清理残留端口占用
for port in "$FRONTEND_PORT" "$BACKEND_PORT"; do
  pids_on_port="$(find_port_pids "$port")"
  for pid_on_port in $pids_on_port; do
    if [ -n "$pid_on_port" ]; then
      echo "清理端口 $port 上的残留进程 (PID $pid_on_port)..."
      kill_tree "$pid_on_port"
      sleep 0.5
    fi
  done
done

# --- 启动后端 ---
echo "启动 Canvas 后端 (端口: $BACKEND_PORT)..."
cd "$BACKEND_DIR"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
if [ ! -x "$VENV_PY" ] || grep -q 'backend/canvas/.venv' "$BACKEND_DIR/.venv/pyvenv.cfg" 2>/dev/null; then
  echo "重建 Python 虚拟环境..."
  rm -rf "$BACKEND_DIR/.venv"
  python3 -m venv "$BACKEND_DIR/.venv"
  VENV_PY="$BACKEND_DIR/.venv/bin/python"
  VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"
fi
"$VENV_PY" -m pip install -r requirements.txt 2>&1 | tail -3

start_backend() {
  nohup "$VENV_UVICORN" main:app --host 0.0.0.0 --port "$BACKEND_PORT" > "$LOG_DIR/canvas-backend-dev.log" 2>&1 &
  echo $! > "$LOG_DIR/canvas-backend-dev.pid"
}

start_backend
sleep 0.5
if ! pid_alive "$LOG_DIR/canvas-backend-dev.pid" || ! wait_http_post_ok "canvas-backend" "http://127.0.0.1:$BACKEND_PORT/health" 20; then
  echo "canvas-backend 首次启动失败，尝试重启一次..."
  if pid_alive "$LOG_DIR/canvas-backend-dev.pid"; then
    kill_tree "$(cat "$LOG_DIR/canvas-backend-dev.pid")"
    sleep 1
  fi
  start_backend
  sleep 0.5
  if ! pid_alive "$LOG_DIR/canvas-backend-dev.pid" || ! wait_http_post_ok "canvas-backend" "http://127.0.0.1:$BACKEND_PORT/health" 20; then
    echo "canvas-backend 启动失败，最近日志："
    tail -n 120 "$LOG_DIR/canvas-backend-dev.log" || true
    exit 1
  fi
fi

# --- 启动前端 ---
echo "启动 Canvas 前端 (端口: $FRONTEND_PORT)..."
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install 2>&1 | tail -3
fi
nohup npm run dev -- --port "$FRONTEND_PORT" > "$LOG_DIR/canvas-frontend-dev.log" 2>&1 &
echo $! > "$LOG_DIR/canvas-frontend-dev.pid"
sleep 0.5
if ! pid_alive "$LOG_DIR/canvas-frontend-dev.pid" || ! wait_http_ok "canvas-frontend" "http://127.0.0.1:$FRONTEND_PORT/" 25; then
  echo "canvas-frontend 启动失败，最近日志："
  tail -n 120 "$LOG_DIR/canvas-frontend-dev.log" || true
  exit 1
fi

echo ""
echo "=========================================="
echo "  Canvas 开发环境启动成功！"
echo "  前端: http://127.0.0.1:$FRONTEND_PORT/novel/login"
echo "  后端: http://127.0.0.1:$BACKEND_PORT"
echo "=========================================="
