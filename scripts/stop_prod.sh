#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/backend-prod.pid"

# --- 读取端口配置 ---
read_port_config() {
  local cfg="$ROOT_DIR/config.json"
  if [ ! -f "$cfg" ]; then
    return 0
  fi
  PROD_PORT="$(python3 -c '
import json
from pathlib import Path
cfg = json.loads(Path("'"$cfg"'").read_text(encoding="utf-8"))
print(cfg["app"]["prod_port"])
' 2>/dev/null || true)"
}

kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

kill_backend_by_cmdline() {
  local pids
  pids="$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port $PROD_PORT" 2>/dev/null || true)"
  for p in $pids; do
    kill "$p" 2>/dev/null || true
  done
}

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "停止后端 (PID $PID)..."
    kill_tree "$PID"
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# 清理残留端口
read_port_config
kill_backend_by_cmdline
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

echo "prod backend stopped"
