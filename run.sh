#!/usr/bin/env bash
# Boot: restart host gpsd + Kismet, API image, compose up.
# Does not install packages — run ./deploy.sh once first for that.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== wardrivrr ==="

[[ -f .env ]] || { echo "Missing .env - run ./deploy.sh first."; exit 1; }

require_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  echo "Root is required to (re)start gpsd, Kismet, and helper systemd units."
  read -r -p "Continue and authenticate with sudo? [Y/n]: " ok
  ok=${ok:-Y}
  if [[ ! "$ok" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
  sudo -v
}

require_root
# shellcheck disable=SC1091
source "$ROOT/scripts/ensure_docker.sh"
ensure_docker || {
  echo "Docker setup failed — run ./deploy.sh once, or install Docker Engine + Compose v2."
  exit 1
}

set -a
# shellcheck disable=SC1091
source .env
set +a

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
fix_env_kv HOST_PROJECT "$ROOT"
fix_env_kv HOST_DATA_ROOT "$ROOT/data"
# Same path as HOST_PROJECT so API→docker compose resolves host bind mounts
fix_env_kv WARDRIVRR_COMPOSE_ROOT "$ROOT"
fix_env_kv VALHALLA_URL "http://127.0.0.1:8002"

if ! grep -qE '^VALHALLA_SERVER_THREADS=' .env 2>/dev/null; then
  _n="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
  _t=$((_n - 1))
  [[ "$_t" -lt 2 ]] && _t=2
  [[ "$_t" -gt 12 ]] && _t=12
  fix_env_kv VALHALLA_SERVER_THREADS "$_t"
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

IMAGE="${WARDRIVRR_IMAGE:-wardrivrr-api:local}"
export WARDRIVRR_IMAGE="$IMAGE"
FORCE_LOCAL_BUILD="${FORCE_LOCAL_BUILD:-1}"

echo "Image: $WARDRIVRR_IMAGE  arch=$(uname -m)  FORCE_LOCAL_BUILD=$FORCE_LOCAL_BUILD"

mkdir -p data/kismet_logs/wardrivrr data/valhalla data/pbf data/incoming
OWNER="${SUDO_USER:-${USER:-}}"
[[ -n "$OWNER" ]] && sudo chown -R "$OWNER:$OWNER" data 2>/dev/null || true
chmod -R a+rwX data/kismet_logs 2>/dev/null || true
chmod a+rx postgis postgis/init 2>/dev/null || true
chmod a+r postgis/init/*.sql 2>/dev/null || true
if [[ -d data/valhalla/active.osm.pbf ]]; then
  sudo rm -rf data/valhalla/active.osm.pbf 2>/dev/null || rm -rf data/valhalla/active.osm.pbf || true
fi

# Valhalla active.osm.pbf is produced by the API for the selected level
# (city/district clip) — never auto-seed from a full regional pack.

# gpsd
if [[ ! -f /etc/default/gpsd ]] || ! grep -q '^DEVICES=' /etc/default/gpsd 2>/dev/null; then
  GPS_DEV="/dev/ttyACM0"
  [[ -e /dev/ttyUSB0 ]] && GPS_DEV="/dev/ttyUSB0"
  [[ -e /dev/ttyACM0 ]] && GPS_DEV="/dev/ttyACM0"
  # No -G: gpsd only needs to serve host-local clients (API, Kismet)
  sudo tee /etc/default/gpsd >/dev/null <<EOF
DEVICES="$GPS_DEV"
GPSD_OPTIONS="-n"
USBAUTO="true"
START_DAEMON="true"
EOF
fi
sudo systemctl disable --now gpsd.socket 2>/dev/null || true
sudo systemctl enable gpsd 2>/dev/null || true
sudo systemctl restart gpsd 2>/dev/null || sudo systemctl start gpsd 2>/dev/null || true
echo "gpsd: $(systemctl is-active gpsd 2>/dev/null || echo unknown)"

# Kismet — keep site conf httpd auth in sync with .env, then install + restart
if [[ -s deploy/kismet/kismet_site.conf ]]; then
  _ku="$(grep -E '^KISMET_USER=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  _kp="$(grep -E '^KISMET_PASSWORD=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ -n "$_ku" ]]; then
    sed -i -E "s|^httpd_username=.*|httpd_username=${_ku}|" deploy/kismet/kismet_site.conf
  fi
  if [[ -n "$_kp" ]]; then
    sed -i -E "s|^httpd_password=.*|httpd_password=${_kp}|" deploy/kismet/kismet_site.conf
  fi
  sudo mkdir -p /etc/kismet
  sudo cp -f deploy/kismet/kismet_site.conf /etc/kismet/kismet_site.conf
elif [[ ! -s /etc/kismet/kismet_site.conf ]]; then
  echo "WARNING: no kismet_site.conf - run ./deploy.sh"
fi
if command -v kismet >/dev/null 2>&1; then
  sudo systemctl disable --now wardrivrr-kismet 2>/dev/null || true
  sudo systemctl enable kismet 2>/dev/null || true
  sudo systemctl restart kismet 2>/dev/null || sudo systemctl start kismet 2>/dev/null || true
  echo "kismet: $(systemctl is-active kismet 2>/dev/null || echo unknown)"
else
  echo "kismet: not installed (run ./deploy.sh)"
fi

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env)
"${COMPOSE[@]}" config --quiet

PULLED=0
if [[ "$FORCE_LOCAL_BUILD" != "1" ]]; then
  if docker pull "$WARDRIVRR_IMAGE"; then
    echo "Using GHCR image."
    PULLED=1
  else
    echo "GHCR pull failed - local build."
  fi
fi
if [[ "$PULLED" != "1" ]]; then
  echo "Building API image..."
  "${COMPOSE[@]}" build api
fi

SERVICES=(api postgis)
if [[ -f data/valhalla/active.osm.pbf ]] && [[ -s data/valhalla/active.osm.pbf ]]; then
  SERVICES+=(valhalla)
  echo "Valhalla: starting (level extract already present)"
else
  echo "Valhalla: skipped until a level is created"
  "${COMPOSE[@]}" stop valhalla >/dev/null 2>&1 || true
fi

"${COMPOSE[@]}" up -d --remove-orphans "${SERVICES[@]}"

if [[ -f deploy/wardrivrr-stack.service ]]; then
  # Rewrite /opt/wardrivrr placeholders to this clone so boot works off-path.
  _unit="$(mktemp)"
  sed "s|/opt/wardrivrr|$ROOT|g" deploy/wardrivrr-stack.service >"$_unit"
  # Prefer GHCR/local image from .env — do not force a rebuild every boot.
  sed -i '/^Environment=FORCE_LOCAL_BUILD=/d' "$_unit" 2>/dev/null \
    || sed -i '' '/^Environment=FORCE_LOCAL_BUILD=/d' "$_unit" 2>/dev/null \
    || true
  sudo cp -f "$_unit" /etc/systemd/system/wardrivrr-stack.service
  rm -f "$_unit"
  sudo systemctl daemon-reload
  sudo systemctl enable wardrivrr-stack docker gpsd kismet 2>/dev/null || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "API:    http://${IP:-127.0.0.1}:8000/"
echo "Status: http://${IP:-127.0.0.1}:8000/status"
echo "Kismet: http://${IP:-127.0.0.1}:2501/"

if command -v curl >/dev/null 2>&1; then
  echo -n "Waiting for API"
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
  if [[ "$HEALTHY" != "1" ]]; then
    echo "API not ready after 90s"
    "${COMPOSE[@]}" ps
    exit 1
  fi
  echo "API health: ok"
fi
echo "Boot complete."
