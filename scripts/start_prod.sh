#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
DEPLOY_DIR="$ROOT_DIR/deploy"
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

if [ -f "$RUN_DIR/backend-prod.pid" ]; then
  old_pid="$(cat "$RUN_DIR/backend-prod.pid" 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "停止旧后端 (PID $old_pid)..."
    kill_tree "$old_pid"
    sleep 1
  fi
  rm -f "$RUN_DIR/backend-prod.pid"
fi

# 清理残留端口
pids_on_port="$(ss -tlnp "sport = :$PROD_PORT" 2>/dev/null | grep -oP 'pid=\K\d+' || true)"
for pid_on_port in $pids_on_port; do
  if [ -n "$pid_on_port" ]; then
    kill "$pid_on_port" 2>/dev/null || true
  fi
done

# --- 构建前端 ---
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install 2>&1 | tail -3
fi
npm run build
rm -rf "$DEPLOY_DIR/novel"/*
cp -r dist/* "$DEPLOY_DIR/novel/"

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
deactivate

cat <<'NGINX'
Production static files are ready in deploy/novel.
Use Nginx location example:
location /novel/ {
  alias /root/Novel/deploy/novel/;
  try_files $uri $uri/ /novel/index.html;
}
NGINX
