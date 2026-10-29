#!/usr/bin/env bash
# One-shot: gpsd on ttyACM0 + ensure Kismet up. Run on the mini (teslian).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GPS_DEV="${1:-/dev/ttyACM0}"

echo "=== gpsd → $GPS_DEV (localhost only; no -G) ==="
if [[ ! -e "$GPS_DEV" ]]; then
  echo "WARNING: $GPS_DEV not present yet — gpsd will start anyway (USBAUTO)."
fi
sudo tee /etc/default/gpsd >/dev/null <<EOF
DEVICES="$GPS_DEV"
GPSD_OPTIONS="-n"
USBAUTO="true"
START_DAEMON="true"
EOF
sudo systemctl enable --now gpsd
sudo systemctl restart gpsd
sleep 1
ss -lntp | grep 2947 || echo "gpsd not listening yet"

echo "=== Kismet log dir + service ==="
mkdir -p data/kismet_logs/wardrivrr
chmod -R a+rwX data/kismet_logs || true
sudo systemctl enable --now kismet
sudo systemctl restart kismet || true
sleep 1
ss -lntp | grep 2501 || echo "kismet not on 2501"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
  echo "=== curl Kismet as ${KISMET_USER:-?} ==="
  curl -fsS -u "${KISMET_USER}:${KISMET_PASSWORD}" \
    http://127.0.0.1:2501/system/status.json | head -c 200
  echo
fi

echo "=== Recreate API with host networking (after git pull) ==="
echo "  git pull && docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env up -d --force-recreate api"
echo "Done. BT already runs via Kismet hci0; Alfa = uncomment source=wlx when plugged in."
