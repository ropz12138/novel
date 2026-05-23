#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
NGINX_HTML_DIR="/usr/local/nginx/html"
DEPLOY_DIR="$NGINX_HTML_DIR"
RUN_DIR="$ROOT_DIR/.run"

mkdir -p "$DEPLOY_DIR/novel" "$RUN_DIR"

# --- 读取端口配置 ---
read_port_config() {
  local cfg="$ROOT_DIR/config.json"
  if [ ! -f "$cfg" ]; then
    echo "缺少配置文件: $cfg"
    return 1
  fi
  PROD_PORT="$(python3 -c '
import json
from pathlib import Path
cfg = json.loads(Path("'"$cfg"'").read_text(encoding="utf-8"))
print(cfg["app"]["prod_port"])
')"
}

read_port_config

# --- 清理旧后端进程 ---
kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

is_pid_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

is_port_listening() {
  ss -ltn "sport = :$PROD_PORT" 2>/dev/null | grep -q ":$PROD_PORT\b"
}

kill_backend_by_cmdline() {
  local pids
  pids="$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $PROD_PORT" 2>/dev/null || true)"
  for p in $pids; do
    kill "$p" 2>/dev/null || true
  done
}

if [ -f "$RUN_DIR/backend-prod.pid" ]; then
  old_pid="$(cat "$RUN_DIR/backend-prod.pid" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "停止旧后端 (PID $old_pid)..."
    kill_tree "$old_pid"
    sleep 1
  fi
  rm -f "$RUN_DIR/backend-prod.pid"
fi

# 按命令行兜底清理同端口后端
kill_backend_by_cmdline
sleep 1

# 清理残留端口（优先 fuser，回退 ss）
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PROD_PORT}/tcp" 2>/dev/null || true
else
  pids_on_port="$(ss -tlnp "sport = :$PROD_PORT" 2>/dev/null | grep -oP 'pid=\K\d+' || true)"
  for pid_on_port in $pids_on_port; do
    if [ -n "$pid_on_port" ]; then
      kill "$pid_on_port" 2>/dev/null || true
    fi
  done
fi
sleep 1

# --- 构建前端 ---
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install 2>&1 | tail -3
fi
npm run build
rm -rf "$DEPLOY_DIR/novel"/*
cp -r dist/* "$DEPLOY_DIR/novel/"
# 确保 nginx worker 可读静态文件，避免 403（受运行用户 umask 影响时尤为必要）
find "$DEPLOY_DIR/novel" -type d -exec chmod 755 {} \;
find "$DEPLOY_DIR/novel" -type f -exec chmod 644 {} \;

# --- 启动后端 ---
cd "$BACKEND_DIR"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy ftp_proxy FTP_PROXY
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt 2>&1 | tail -3
nohup uvicorn app.main:app --host 0.0.0.0 --port "$PROD_PORT" --workers 2 > "$RUN_DIR/backend-prod.log" 2>&1 &
echo $! > "$RUN_DIR/backend-prod.pid"

# --- 启动成功校验 ---
backend_pid="$(cat "$RUN_DIR/backend-prod.pid" 2>/dev/null || true)"
started_ok=0
for _ in $(seq 1 20); do
  if grep -q "Application startup complete\|Uvicorn running on" "$RUN_DIR/backend-prod.log" 2>/dev/null; then
    started_ok=1
    break
  fi
  if is_port_listening; then
    started_ok=1
    break
  fi
  sleep 0.5
done

if [ "$started_ok" -ne 1 ]; then
  echo "ERROR: backend failed to start on port $PROD_PORT"
  echo "---- backend-prod.log (tail) ----"
  tail -n 80 "$RUN_DIR/backend-prod.log" || true
  exit 1
fi

# 如果初始后台 PID 已退出，尝试回填真实 uvicorn 主进程 PID
if ! is_pid_alive "$backend_pid"; then
  real_pid="$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $PROD_PORT" | head -n 1 || true)"
  if [ -n "$real_pid" ]; then
    echo "$real_pid" > "$RUN_DIR/backend-prod.pid"
  fi
fi
deactivate

cat <<'NGINX'
Production static files are ready in /usr/local/nginx/html/novel.
Nginx location config (nginx-novel-locations.conf):
  alias /usr/local/nginx/html/novel/;
  try_files $uri $uri/ /novel/index.html;
NGINX
