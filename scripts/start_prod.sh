#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
DEPLOY_DIR="$ROOT_DIR/deploy"
RUN_DIR="$ROOT_DIR/.run"

mkdir -p "$DEPLOY_DIR/novel" "$RUN_DIR"

cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  npm install >/dev/null
fi
npm run build
rm -rf "$DEPLOY_DIR/novel"/*
cp -r dist/* "$DEPLOY_DIR/novel/"

cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt >/dev/null
nohup uvicorn app.main:app --host 0.0.0.0 --port 9001 > "$RUN_DIR/backend-prod.log" 2>&1 &
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
