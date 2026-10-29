#!/usr/bin/env bash
# Boot: restart host gpsd, ensure host Kismet is off, compose up (incl. wardrivrr_kismet).
# Does not install packages — run ./deploy.sh once first, or use plain docker compose.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== wardrivrr ==="

[[ -f .env ]] || { echo "Missing .env - run ./deploy.sh first."; exit 1; }

require_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  echo "Root is required to (re)start gpsd and helper systemd units."
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

# gpsd (required)
if [[ ! -f /etc/default/gpsd ]] || ! grep -q '^DEVICES=' /etc/default/gpsd 2>/dev/null; then
  echo "ERROR: gpsd not configured — run ./deploy.sh once (GPS receiver required)."
  exit 1
fi
sudo systemctl disable --now gpsd.socket 2>/dev/null || true
sudo systemctl enable gpsd 2>/dev/null || true
sudo systemctl restart gpsd 2>/dev/null || sudo systemctl start gpsd 2>/dev/null || true
echo "gpsd: $(systemctl is-active gpsd 2>/dev/null || echo unknown)"

# Host Kismet must stay off — Compose owns wardrivrr_kismet on :2501/:3501
sudo systemctl disable --now kismet 2>/dev/null || true
sudo systemctl disable --now wardrivrr-kismet 2>/dev/null || true
if systemctl is-active kismet >/dev/null 2>&1; then
  echo "ERROR: host kismet.service is still active — stop it before Compose Kismet can start."
  exit 1
fi

# Seed Compose conf from deploy template / .env if data conf missing
mkdir -p data/kismet data/kismet_logs/wardrivrr
if [[ -s deploy/kismet/kismet_site.conf ]]; then
  _ku="$(grep -E '^KISMET_USER=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  _kp="$(grep -E '^KISMET_PASSWORD=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  if [[ -n "$_ku" ]]; then
    sed -i -E "s|^httpd_username=.*|httpd_username=${_ku}|" deploy/kismet/kismet_site.conf
  fi
  if [[ -n "$_kp" ]]; then
    sed -i -E "s|^httpd_password=.*|httpd_password=${_kp}|" deploy/kismet/kismet_site.conf
  fi
  if [[ ! -s data/kismet/kismet_site.conf ]]; then
    cp -f deploy/kismet/kismet_site.conf data/kismet/kismet_site.conf
  fi
elif [[ ! -s data/kismet/kismet_site.conf ]]; then
  echo "WARNING: no data/kismet/kismet_site.conf — configure Machine setup in the UI"
fi

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.host.yml --env-file .env)
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

SERVICES=(api postgis kismet)
if [[ -f data/valhalla/active.osm.pbf ]] && [[ -s data/valhalla/active.osm.pbf ]]; then
  SERVICES+=(valhalla)
  echo "Valhalla: starting (level extract already present)"
else
  echo "Valhalla: skipped until a level is created"
  "${COMPOSE[@]}" stop valhalla >/dev/null 2>&1 || true
fi

"${COMPOSE[@]}" up -d --remove-orphans "${SERVICES[@]}"
echo "kismet: compose wardrivrr_kismet"

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
  sudo systemctl enable wardrivrr-stack docker gpsd 2>/dev/null || true
  sudo systemctl disable kismet 2>/dev/null || true
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "API:    http://${IP:-127.0.0.1}:1337/"
echo "Status: http://${IP:-127.0.0.1}:1337/status"
echo "Kismet: http://${IP:-127.0.0.1}:2501/"

if command -v curl >/dev/null 2>&1; then
  echo -n "Waiting for API"
  HEALTHY=0
  for _ in {1..45}; do
    if curl -fsS --max-time 2 http://127.0.0.1:1337/api/health >/dev/null 2>&1; then
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
