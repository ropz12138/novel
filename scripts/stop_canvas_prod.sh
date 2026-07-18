#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do kill_tree "$child"; done
  kill "$pid" 2>/dev/null || true
}

PID_FILE="$RUN_DIR/canvas-backend-prod.pid"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "停止 canvas-backend (PID $PID)..."
    kill_tree "$PID"
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# 兜底清理残留进程
PROD_PORT="$(python3 -c "
import json
cfg = json.loads(open('$ROOT_DIR/config.json', encoding='utf-8').read())
print(cfg['app']['prod_port'])
" 2>/dev/null || true)"

if [ -n "$PROD_PORT" ]; then
  pids="$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $PROD_PORT" 2>/dev/null || true)"
  for p in $pids; do kill "$p" 2>/dev/null || true; done
  fuser -k "${PROD_PORT}/tcp" 2>/dev/null || true
fi

echo "Canvas 生产环境已停止"
