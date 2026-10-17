#!/usr/bin/env bash
# Local debug runner — PostGIS + host API (run_dev.py). Not for the car mini-PC.
set -euo pipefail
cd "$(dirname "$0")"

if [[ -x "venv/bin/python" ]]; then
  PY="venv/bin/python"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
elif [[ -x "venv/Scripts/python.exe" ]]; then
  PY="venv/Scripts/python.exe"
else
  PY="python3"
fi

echo "[wardrivrr] debug: $PY run_dev.py $*"
exec "$PY" run_dev.py "$@"
