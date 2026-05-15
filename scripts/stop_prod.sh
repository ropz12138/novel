#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/backend-prod.pid"

kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
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
pids_on_port="$(ss -tlnp "sport = :9001" 2>/dev/null | grep -oP 'pid=\K\d+' || true)"
for pid_on_port in $pids_on_port; do
  if [ -n "$pid_on_port" ]; then
    kill "$pid_on_port" 2>/dev/null || true
  fi
done

echo "prod backend stopped"
