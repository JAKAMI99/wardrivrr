#!/usr/bin/env sh
# Seed offline geographic data into the app data volume / image build context.
# PostGIS, routing, and Kismet are separate containers — not handled here.
#
# Usage (from repo root):
#   sh docker/prepare-data.sh
#   sh docker/prepare-data.sh --force
#
# Intended as the data stage for a future app Dockerfile, e.g.:
#   RUN python scripts/prepare_offline_data.py

set -eu
cd "$(dirname "$0")/.."

if [ -x "venv/bin/python" ]; then
  PY=venv/bin/python
elif [ -x ".venv/bin/python" ]; then
  PY=.venv/bin/python
else
  PY=python3
fi

echo "[docker/prepare-data] using $PY"
exec "$PY" scripts/prepare_offline_data.py "$@"
