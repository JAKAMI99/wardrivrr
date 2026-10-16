#!/usr/bin/env bash
# Fire-and-forget boot: host gpsd + Kismet, local API image, compose up.
# gpsd/Kismet stay on the host; API uses host networking (see deploy/compose.car.yml).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing .env — run ./scripts/car_setup.sh first."
  exit 1
fi

# shellcheck disable=SC1091
set -a
# shellcheck source=/dev/null
source .env
set +a

# Normalize leftover Docker-bridge hostnames (host-network API needs localhost)
fix_env_kv() {
  local key="$1" val="$2"
  if grep -qE "^${key}=" .env 2>/dev/null; then
    sed -i.bak -E "s|^${key}=.*|${key}=${val}|" .env && rm -f .env.bak
  else
    echo "${key}=${val}" >>.env
  fi
}
fix_env_kv GPSD_HOST 127.0.0.1
fix_env_kv KISMET_URL "http://127.0.0.1:2501"
fix_env_kv FORCE_LOCAL_BUILD "${FORCE_LOCAL_BUILD:-1}"
# shellcheck disable=SC1091
set -a; source .env; set +a

if ! docker info >/dev/null 2>&1; then
  echo "Cannot talk to Docker. Fix once: sudo usermod -aG docker \"\$USER\" && newgrp docker"
  exit 1
fi

IMAGE="${WARDRIVRR_IMAGE:-wardrivrr-api:local}"
export WARDRIVRR_IMAGE="$IMAGE"
FORCE_LOCAL_BUILD="${FORCE_LOCAL_BUILD:-1}"

echo "=== wardrivrr car_up ==="
echo "Image: $WARDRIVRR_IMAGE  arch=$(uname -m)  FORCE_LOCAL_BUILD=$FORCE_LOCAL_BUILD"

# --- Host dirs / perms (idempotent) ---
mkdir -p data/kismet_logs/wardrivrr data/valhalla data/incoming
chmod -R a+rwX data/kismet_logs 2>/dev/null || true
chmod a+rx postgis postgis/init 2>/dev/null || true
chmod a+r postgis/init/*.sql 2>/dev/null || true
if [[ -d data/valhalla/active.osm.pbf ]]; then
  echo "Removing bogus data/valhalla/active.osm.pbf directory…"
  sudo rm -rf data/valhalla/active.osm.pbf 2>/dev/null || rm -rf data/valhalla/active.osm.pbf
fi

# --- gpsd (TCP for Status / API on host net) ---
if [[ ! -f /etc/default/gpsd ]] || ! grep -q -- '-G' /etc/default/gpsd 2>/dev/null; then
  GPS_DEV="/dev/ttyACM0"
  [[ -e /dev/ttyUSB0 ]] && GPS_DEV="/dev/ttyUSB0"
  [[ -e /dev/ttyACM0 ]] && GPS_DEV="/dev/ttyACM0"
  echo "Configuring gpsd ($GPS_DEV, -G)…"
  sudo tee /etc/default/gpsd >/dev/null <<EOF
DEVICES="$GPS_DEV"
GPSD_OPTIONS="-n -G"
USBAUTO="true"
START_DAEMON="true"
EOF
fi
sudo systemctl disable --now gpsd.socket 2>/dev/null || true
sudo systemctl enable gpsd 2>/dev/null || true
sudo systemctl restart gpsd 2>/dev/null || sudo systemctl start gpsd 2>/dev/null || true
echo "gpsd: $(systemctl is-active gpsd 2>/dev/null || echo unknown)"

# --- Kismet site conf + package service ---
if [[ -s deploy/kismet/kismet_site.conf ]]; then
  sudo mkdir -p /etc/kismet
  sudo cp -f deploy/kismet/kismet_site.conf /etc/kismet/kismet_site.conf
elif [[ -s /etc/kismet/kismet_site.conf ]]; then
  :
else
  echo "WARNING: no kismet_site.conf — RF UI may be empty until car_setup."
fi
if command -v kismet >/dev/null 2>&1; then
  sudo systemctl disable --now wardrivrr-kismet 2>/dev/null || true
  sudo systemctl enable kismet 2>/dev/null || true
  sudo systemctl restart kismet 2>/dev/null || sudo systemctl start kismet 2>/dev/null || true
  echo "kismet: $(systemctl is-active kismet 2>/dev/null || echo unknown)"
else
  echo "kismet: not installed (run car_setup later)"
fi

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env)
"${COMPOSE[@]}" config --quiet

PULLED=0
if [[ "$FORCE_LOCAL_BUILD" != "1" ]]; then
  if docker pull "$WARDRIVRR_IMAGE"; then
    echo "Using GHCR image."
    PULLED=1
  else
    echo "GHCR pull failed — local build."
  fi
fi
if [[ "$PULLED" != "1" ]]; then
  echo "Building API image locally…"
  "${COMPOSE[@]}" build api
fi

SERVICES=(api postgis)
if [[ -f data/valhalla/active.osm.pbf ]] && [[ -s data/valhalla/active.osm.pbf ]]; then
  SERVICES+=(valhalla)
else
  echo "Valhalla: skipped (no active.osm.pbf — prepare a level when ready)."
  "${COMPOSE[@]}" stop valhalla >/dev/null 2>&1 || true
fi

"${COMPOSE[@]}" up -d --remove-orphans "${SERVICES[@]}"

# Ensure stack + gpsd + kismet survive reboot
if [[ -f deploy/wardrivrr-stack.service ]]; then
  sudo cp -f deploy/wardrivrr-stack.service /etc/systemd/system/wardrivrr-stack.service
  sudo systemctl daemon-reload
  sudo systemctl enable wardrivrr-stack docker gpsd kismet 2>/dev/null || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "API:    http://${IP:-127.0.0.1}:8000/"
echo "Status: http://${IP:-127.0.0.1}:8000/status"
echo "Kismet: http://${IP:-127.0.0.1}:2501/"

if command -v curl >/dev/null 2>&1; then
  echo -n "Waiting for API health"
  HEALTHY=0
  for _ in {1..45}; do
    if curl -fsS --max-time 2 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
      HEALTHY=1
      break
    fi
    echo -n "."
    sleep 2
  done
  echo
  if [[ "$HEALTHY" == "1" ]]; then
    echo "API health: ok"
  else
    echo "API health: not ready after 90s"
    "${COMPOSE[@]}" ps
    exit 1
  fi
fi
echo "Boot complete."
