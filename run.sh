#!/usr/bin/env bash
# Everyday car / mini-PC boot — compose up, gpsd check, Valhalla seed.
# First time on this machine: ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -f .env ]]; then
  echo "Missing .env — run ./deploy.sh first."
  exit 1
fi
exec ./scripts/car_up.sh "$@"
