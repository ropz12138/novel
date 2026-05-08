#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

for svc in frontend-dev backend-dev; do
  PID_FILE="$RUN_DIR/${svc}.pid"
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" >/dev/null 2>&1; then
      kill "$PID"
    fi
    rm -f "$PID_FILE"
  fi
done

echo "dev stopped"
