#!/usr/bin/env bash
# Local host API + PostGIS (run_dev.py). Not for onboard deploy.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x venv/bin/python ]]; then PY=venv/bin/python
elif [[ -x .venv/bin/python ]]; then PY=.venv/bin/python
elif [[ -x venv/Scripts/python.exe ]]; then PY=venv/Scripts/python.exe
else PY=python3
fi
exec "$PY" run_dev.py "$@"
