#!/usr/bin/env bash
# First-time car / mini-PC deploy (Wi-Fi, BT, GPS, .env, GHCR / local image).
# Later boots: ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
exec ./scripts/car_setup.sh "$@"
