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

# Host paths so the API container can docker-run osmium / compose-up Valhalla.
# HOST_* are paths on the mini-PC; WARDRIVRR_COMPOSE_ROOT is the in-container mount.
fix_env_kv HOST_PROJECT "$ROOT"
fix_env_kv HOST_DATA_ROOT "$ROOT/data"
fix_env_kv WARDRIVRR_COMPOSE_ROOT "/host/project"
fix_env_kv VALHALLA_URL "http://127.0.0.1:8002"
# shellcheck disable=SC1091
set -a; source .env; set +a

# --- Host dirs / perms (idempotent) ---
mkdir -p data/kismet_logs/wardrivrr data/valhalla data/pbf data/incoming
sudo chown -R jakami:jakami data 2>/dev/null || true
chmod -R a+rwX data/kismet_logs 2>/dev/null || true
chmod a+rx postgis postgis/init 2>/dev/null || true
chmod a+r postgis/init/*.sql 2>/dev/null || true
if [[ -d data/valhalla/active.osm.pbf ]]; then
  echo "Removing bogus data/valhalla/active.osm.pbf directory…"
  sudo rm -rf data/valhalla/active.osm.pbf 2>/dev/null || rm -rf data/valhalla/active.osm.pbf || true
fi

# Regional packs are data/pbf/{GeofabrikId}.osm.pbf (e.g. Arnsberg…).
# Valhalla only mounts data/valhalla/ — seed active.osm.pbf from the largest pack.
pick_regional_pbf() {
  local f best="" best_sz=0 sz
  shopt -s nullglob
  for f in data/pbf/*.osm.pbf data/pbf/*.pbf; do
    [[ -f "$f" ]] || continue
    sz=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
    if [[ "$sz" -gt "$best_sz" && "$sz" -ge 1000 ]]; then
      best="$f"
      best_sz=$sz
    fi
  done
  shopt -u nullglob
  [[ -n "$best" ]] && printf '%s' "$best"
}

seed_active_from_regional() {
  local src="$1"
  [[ -n "$src" && -f "$src" ]] || return 1
  mkdir -p data/valhalla
  if [[ -f data/valhalla/active.osm.pbf ]]; then
    local asz ssz
    asz=$(stat -c%s data/valhalla/active.osm.pbf 2>/dev/null || echo 0)
    ssz=$(stat -c%s "$src" 2>/dev/null || echo 0)
    # Keep an existing level clip (usually smaller than the regional pack)
    if [[ -f data/valhalla/active.json ]] && grep -q '"mode": "clip"' data/valhalla/active.json 2>/dev/null; then
      echo "Valhalla: keeping level clip active.osm.pbf"
      return 0
    fi
    if [[ "$asz" == "$ssz" && "$asz" -ge 1000 ]]; then
      echo "Valhalla: active.osm.pbf already seeded from regional pack"
      return 0
    fi
  fi
  echo "Valhalla: seeding active.osm.pbf from $src"
  rm -f data/valhalla/active.osm.pbf
  if ln "$src" data/valhalla/active.osm.pbf 2>/dev/null; then
    :
  else
    cp -f "$src" data/valhalla/active.osm.pbf
  fi
  cat >data/valhalla/active.json <<EOF
{"mode": "seed", "source_pbf": "$src", "updated_at": $(date +%s)}
EOF
  # Full tile rebuild from the new feed
  rm -rf data/valhalla/valhalla_tiles
  docker volume rm -f wardrivrr_valhalla_data >/dev/null 2>&1 || true
  return 0
}

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

REGIONAL="$(pick_regional_pbf || true)"
if [[ -n "${REGIONAL:-}" ]]; then
  seed_active_from_regional "$REGIONAL" || true
fi

SERVICES=(api postgis)
if [[ -f data/valhalla/active.osm.pbf ]] && [[ -s data/valhalla/active.osm.pbf ]]; then
  SERVICES+=(valhalla)
  echo "Valhalla: starting (feed data/valhalla/active.osm.pbf)."
else
  echo "Valhalla: skipped (no pack in data/pbf/*.osm.pbf yet — download a region first)."
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
