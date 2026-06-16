#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

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

# --- 停止进程 ---
stop_process() {
  local pid_file="$1" name="$2"
  if [ -f "$pid_file" ]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "停止 $name (PID $pid)..."
      kill_tree "$pid"
      sleep 1
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pid_file"
  fi
}

stop_process "$RUN_DIR/canvas-backend-dev.pid" "canvas-backend"
stop_process "$RUN_DIR/canvas-frontend-dev.pid" "canvas-frontend"

echo "Canvas 开发环境已停止"
