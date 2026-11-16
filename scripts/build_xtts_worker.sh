#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SDK_DIR="$(python3 - "$ROOT_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
config = json.loads((root / "config.json").read_text(encoding="utf-8"))
print((root / config["tts"]["iflytek_xtts"]["sdk_dir"]).resolve())
PY
)"

g++ -std=c++11 -O2 -pthread \
  "$ROOT_DIR/backend/native/xtts_worker.cpp" \
  -I"$SDK_DIR/include" -L"$SDK_DIR/libs" -laikit \
  '-Wl,-rpath,$ORIGIN/../vendor/iflytek_xtts/libs' \
  -o "$ROOT_DIR/backend/native/xtts_worker"

echo "已构建 backend/native/xtts_worker"
