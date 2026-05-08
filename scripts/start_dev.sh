#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
RUN_DIR="$ROOT_DIR/.run"

mkdir -p "$RUN_DIR"

cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt >/dev/null
nohup uvicorn app.main:app --host 0.0.0.0 --port 9001 > "$RUN_DIR/backend-dev.log" 2>&1 &
echo $! > "$RUN_DIR/backend-dev.pid"
deactivate

cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install >/dev/null
fi
nohup npm run dev > "$RUN_DIR/frontend-dev.log" 2>&1 &
echo $! > "$RUN_DIR/frontend-dev.pid"

echo "dev started: frontend=9000 backend=9001"
