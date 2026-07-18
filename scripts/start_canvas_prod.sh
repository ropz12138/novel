#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend/canvas"
NGINX_HTML="/usr/local/nginx/html"
RUN_DIR="$ROOT_DIR/.run"

mkdir -p "$NGINX_HTML/novel" "$RUN_DIR"

# --- 读取端口配置 ---
read_port_config() {
  local cfg="$ROOT_DIR/config.json"
  python3 -c "
import json
cfg = json.loads(open('$cfg', encoding='utf-8').read())
print(cfg['app']['prod_port'])
print(cfg['frontend']['prod_port'])
"
}
mapfile -t _ports < <(read_port_config)
PROD_PORT="${_ports[0]}"
FRONTEND_PROD_PORT="${_ports[1]}"

# --- 工具函数 ---
kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

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

kill_backend_by_cmdline() {
  local pids
  pids="$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $PROD_PORT" 2>/dev/null || true)"
  for p in $pids; do kill "$p" 2>/dev/null || true; done
}

# --- 清理旧进程 ---
cleanup_old "$RUN_DIR/canvas-backend-prod.pid" "canvas-backend"

kill_backend_by_cmdline
sleep 1

if command -v fuser >/dev/null 2>&1; then
  fuser -k "${PROD_PORT}/tcp" 2>/dev/null || true
fi
sleep 1

# --- 构建前端 ---
echo "构建前端..."
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install 2>&1 | tail -3
fi
npm run build
rm -rf "$NGINX_HTML/novel"/*
cp -r dist/* "$NGINX_HTML/novel/"
find "$NGINX_HTML/novel" -type d -exec chmod 755 {} \;
find "$NGINX_HTML/novel" -type f -exec chmod 644 {} \;
echo "前端构建完成"

# --- 启动后端 ---
echo "启动 Canvas 后端 (端口: $PROD_PORT)..."
cd "$BACKEND_DIR"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy ftp_proxy FTP_PROXY
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt 2>&1 | tail -3

# --- 数据库迁移（幂等，保证 schema 与 model 一致，避免代码先于迁移导致 500） ---
echo "--- 执行数据库迁移 ---"
python run_migrations.py

nohup uvicorn app.main:app --host 0.0.0.0 --port "$PROD_PORT" --workers 1 > "$RUN_DIR/canvas-backend-prod.log" 2>&1 &
echo $! > "$RUN_DIR/canvas-backend-prod.pid"
deactivate

# --- 启动校验 ---
backend_pid="$(cat "$RUN_DIR/canvas-backend-prod.pid" 2>/dev/null || true)"
started_ok=0
for _ in $(seq 1 40); do
  if curl --noproxy '*' -fsS -m 2 -X POST -H "Content-Type: application/json" -d '{}' "http://127.0.0.1:$PROD_PORT/health" >/dev/null 2>&1; then
    started_ok=1
    break
  fi
  sleep 0.5
done

if [ "$started_ok" -ne 1 ]; then
  echo "ERROR: canvas-backend 启动失败"
  echo "---- 日志 (tail) ----"
  tail -n 80 "$RUN_DIR/canvas-backend-prod.log" || true
  exit 1
fi

echo ""
echo "=========================================="
echo "  Canvas 生产环境启动成功！"
echo "  后端端口: $PROD_PORT"
echo "  静态文件: $NGINX_HTML/novel"
echo "  确保 nginx 已配置 domain: liyicheng12138.cn"
echo "=========================================="
