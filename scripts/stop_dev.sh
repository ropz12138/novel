#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

# 杀进程树
kill_tree() {
  local pid="$1"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  for child in $children; do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

for svc in frontend-dev backend-dev; do
  PID_FILE="$RUN_DIR/${svc}.pid"
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
      echo "停止 $svc (PID $PID)..."
      kill_tree "$PID"
      sleep 1
      # 确保已退出，未退出则强杀
      if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID" 2>/dev/null || true
      fi
    fi
    rm -f "$PID_FILE"
  fi
done

sleep 1

# 清理可能残留的端口占用
for port in 9000 9001; do
  pids_on_port="$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP 'pid=\K\d+' || true)"
  for pid_on_port in $pids_on_port; do
    if [ -n "$pid_on_port" ]; then
      echo "清理端口 $port 上的残留进程 (PID $pid_on_port)..."
      kill_tree "$pid_on_port"
      sleep 1
      if kill -0 "$pid_on_port" 2>/dev/null; then
        kill -9 "$pid_on_port" 2>/dev/null || true
      fi
    fi
  done
done

echo "dev stopped"
