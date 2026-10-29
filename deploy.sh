#!/usr/bin/env bash
# First-time host mini setup: install/configure gpsd, free host Kismet ports,
# write data/kismet conf + .env, compose up (Kismet runs in Docker — not on the host).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=== wardrivrr setup ==="
echo "Requires: host gpsd + GPS receiver. Do NOT leave a host Kismet install running"
echo "(Compose owns :2501/:3501). Wi‑Fi/BT can also be set later in Machine setup."

require_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  echo
  echo "Root is required for apt installs and systemd (gpsd, docker helpers)."
  read -r -p "Continue and authenticate with sudo? [Y/n]: " ok
  ok=${ok:-Y}
  if [[ ! "$ok" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
  sudo -v
  # Keep sudo warm during long apt / build steps
  (while true; do sudo -n true; sleep 50; kill -0 "$$" || exit; done) 2>/dev/null &
  SUDO_KEEPALIVE_PID=$!
  trap 'kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true' EXIT
}

# Sudo first so ensure_docker can install Engine / Compose if missing.
require_root
# shellcheck disable=SC1091
source "$ROOT/scripts/ensure_docker.sh"
ensure_docker || exit 1

set_env() {
  local key="$1" val="$2" file="${3:-.env}"
  if [[ -f "$file" ]] && grep -qE "^${key}=" "$file"; then
    sed -i.bak -E "s|^${key}=.*|${key}=${val}|" "$file" && rm -f "${file}.bak"
  else
    echo "${key}=${val}" >>"$file"
  fi
}

if ! command -v gpsd >/dev/null 2>&1; then
  echo "Installing gpsd (apt)..."
  sudo apt-get update -qq
  sudo apt-get install -y gpsd gpsd-clients
else
  echo "gpsd: already installed"
fi

GPS_TTY=""
mapfile -t TTYS < <(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true)
if [[ ${#TTYS[@]} -eq 0 ]]; then
  echo "No GPS serial device found."
  read -r -p "GPS device path (blank to skip): " GPS_TTY
else
  echo "GPS devices:"
  for i in "${!TTYS[@]}"; do echo "  [$i] ${TTYS[$i]}"; done
  read -r -p "Pick index [0]: " idx
  idx=${idx:-0}
  GPS_TTY="${TTYS[$idx]:-}"
fi

if [[ -z "$GPS_TTY" ]]; then
  echo "ERROR: a GPS serial device is required (gpsd). Plug in the receiver and re-run."
  exit 1
fi
# No -G: only host-local consumers (API on host network, Compose Kismet).
sudo tee /etc/default/gpsd >/dev/null <<EOF
DEVICES="$GPS_TTY"
GPSD_OPTIONS="-n"
USBAUTO="true"
START_DAEMON="true"
EOF
sudo systemctl disable --now gpsd.socket 2>/dev/null || true
sudo systemctl enable --now gpsd || true
echo "gpsd: $(systemctl is-active gpsd 2>/dev/null || echo unknown) → $GPS_TTY"

# Compose Kismet needs free :2501/:3501 — stop any host install.
if systemctl list-unit-files kismet.service >/dev/null 2>&1 \
  || systemctl is-active kismet >/dev/null 2>&1 \
  || command -v kismet >/dev/null 2>&1; then
  echo "Stopping/disabling host Kismet (Compose provides wardrivrr_kismet)..."
  sudo systemctl disable --now kismet 2>/dev/null || true
  sudo systemctl disable --now wardrivrr-kismet 2>/dev/null || true
fi

echo
echo "Wi‑Fi / Bluetooth / Kismet password: prefer Web UI → Machine setup after first login."
echo "Optional: seed interfaces now for the first Compose Kismet conf."
WLAN=""
mapfile -t WLANS < <(ip -o link show 2>/dev/null | awk -F': ' '/wlan|wlx/{print $2}' || true)
if [[ ${#WLANS[@]} -eq 0 ]]; then
  echo "No wlan/wlx interfaces found."
  read -r -p "Monitor Wi-Fi iface (blank to configure in UI later): " WLAN
else
  echo "Wi-Fi interfaces (monitor adapter, not hotspot uplink):"
  for i in "${!WLANS[@]}"; do echo "  [$i] ${WLANS[$i]}"; done
  read -r -p "Pick index (blank = UI later): " widx
  [[ -n "${widx:-}" ]] && WLAN="${WLANS[$widx]:-}"
fi

echo
hciconfig 2>/dev/null || true
read -r -p "Use Bluetooth HCI? [y/N]: " USE_BT
USE_BT=${USE_BT:-n}
BT_IFACE=""
if [[ "$USE_BT" =~ ^[Yy] ]]; then
  read -r -p "HCI iface [hci0]: " BT_IFACE
  BT_IFACE=${BT_IFACE:-hci0}
fi

mkdir -p deploy/kismet "$ROOT/data/kismet" "$ROOT/data/kismet_logs/wardrivrr"
chmod -R a+rwX "$ROOT/data/kismet_logs" "$ROOT/data/kismet" 2>/dev/null || true
read -r -p "Kismet username [wardrivrr]: " KUSER
KUSER=${KUSER:-wardrivrr}
read -r -s -p "Kismet password (blank = random): " KPASS
echo
if [[ -z "$KPASS" ]]; then
  KPASS="$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  echo "Generated Kismet password (saved in .env / Machine setup seed)."
fi
read -r -p "JWT secret (blank = auto-generate on first API start): " JWT

IMAGE="wardrivrr-api:local"
read -r -p "Local image tag [$IMAGE]: " IMAGE_IN
IMAGE=${IMAGE_IN:-$IMAGE}
read -r -p "Prefer GHCR image instead of local build? [y/N]: " USE_GHCR
USE_GHCR=${USE_GHCR:-n}
if [[ "$USE_GHCR" =~ ^[Yy] ]]; then
  GH_OWNER=""
  if git remote get-url origin >/dev/null 2>&1; then
    GH_OWNER="$(git remote get-url origin | sed -E 's#.*(github.com[:/])([^/]+)/.*#\2#' | tr '[:upper:]' '[:lower:]')"
  fi
  read -r -p "GitHub owner/org for GHCR${GH_OWNER:+ [$GH_OWNER]}: " OWNER_IN
  OWNER_IN=${OWNER_IN:-$GH_OWNER}
  [[ -z "$OWNER_IN" ]] && { echo "Owner required for GHCR."; exit 1; }
  IMAGE="ghcr.io/${OWNER_IN}/wardrivrr:latest"
  read -r -p "WARDRIVRR_IMAGE [$IMAGE]: " IMAGE_IN
  IMAGE=${IMAGE_IN:-$IMAGE}
fi

# Container path for logs (bind-mounted from data/kismet_logs)
LOG_PREFIX="/home/kismet/logs/wardrivrr"
{
  echo "# Generated by deploy.sh - do not commit"
  echo "server_name=wardrivrr"
  echo "httpd_bind_address=${KISMET_HTTPD_BIND:-0.0.0.0}"
  echo "httpd_port=2501"
  echo "httpd_username=${KUSER}"
  echo "httpd_password=${KPASS}"
  echo "gps=gpsd:host=127.0.0.1,port=2947"
  if [[ -n "$WLAN" ]] && ip -o link show "$WLAN" >/dev/null 2>&1; then
    echo "source=${WLAN}:name=MonitorWifi:type=linuxwifi"
  elif [[ -n "$WLAN" ]]; then
    echo "#source=${WLAN}:name=MonitorWifi:type=linuxwifi"
  else
    echo "# No RF sources yet — configure in Machine setup"
  fi
  if [[ -n "$BT_IFACE" ]]; then
    echo "source=${BT_IFACE}:name=linuxbt:type=linuxbluetooth"
  else
    echo "#source=hci0:name=linuxbt:type=linuxbluetooth"
  fi
  echo "log_prefix=${LOG_PREFIX}"
  echo "log_types=kismet,kis_db"
  echo "log_title_timestamp=true"
  echo "channel_hop=true"
  echo "channel_hop_speed=5/sec"
  echo "retry_on_source_error=true"
  echo "remote_capture_listen="
} | tee deploy/kismet/kismet_site.conf >"$ROOT/data/kismet/kismet_site.conf"
echo "Kismet: wrote data/kismet/kismet_site.conf (Compose bind)"

if [[ ! -f .env ]]; then
  if [[ -f deploy/examples/.env.host.example ]]; then
    cp deploy/examples/.env.host.example .env
  else
    cp .env.example .env
  fi
fi
set_env DB_HOST 127.0.0.1
# Fresh installs get a random DB password. An existing PostGIS volume keeps
# the password it was initialised with, so only warn there.
CUR_DB_PASS="$(grep -E '^DB_PASS=' .env 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
if [[ -z "$CUR_DB_PASS" || "$CUR_DB_PASS" == "secure_password_here" ]]; then
  if docker volume ls -q 2>/dev/null | grep -qE '(^|_)pgdata$'; then
    echo "WARNING: DB_PASS is still the default and a PostGIS volume exists."
    echo "  Rotate it: docker exec wardrivrr_postgis psql -U explorer -d wardriving -c \"ALTER USER explorer PASSWORD '<new>'\""
    echo "  then set DB_PASS=<new> in .env and re-run."
  else
    set_env DB_PASS "$(openssl rand -hex 24 2>/dev/null || head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    echo "Generated DB password (saved in .env)."
  fi
fi
set_env GPSD_HOST 127.0.0.1
set_env GPSD_PORT 2947
set_env GPSD_ENABLED 1
set_env KISMET_URL "http://127.0.0.1:2501"
set_env KISMET_USER "$KUSER"
set_env KISMET_PASSWORD "$KPASS"
set_env KISMET_LIVE 1
if [[ -n "$JWT" ]]; then
  set_env JWT_SECRET_KEY "$JWT"
else
  # Drop any copied placeholder so the API can auto-generate data/.jwt_secret
  if [[ -f .env ]] && grep -qE '^JWT_SECRET_KEY=' .env; then
    sed -i.bak -E '/^JWT_SECRET_KEY=/d' .env && rm -f .env.bak
  fi
  echo "JWT_SECRET_KEY left unset — API will write data/.jwt_secret on first start."
fi
set_env WARDRIVRR_IMAGE "$IMAGE"
set_env FORCE_LOCAL_BUILD 1
set_env VALHALLA_URL "http://127.0.0.1:8002"
set_env HOST_PROJECT "$ROOT"
set_env HOST_DATA_ROOT "$ROOT/data"
set_env WARDRIVRR_COMPOSE_ROOT "$ROOT"

if ! grep -qE '^VALHALLA_SERVER_THREADS=' .env 2>/dev/null; then
  _n="$(nproc 2>/dev/null || echo 4)"
  _t=$((_n - 1))
  [[ "$_t" -lt 2 ]] && _t=2
  [[ "$_t" -gt 12 ]] && _t=12
  set_env VALHALLA_SERVER_THREADS "$_t"
fi

FORCE_BUILD=1
export WARDRIVRR_IMAGE="$IMAGE"
export FORCE_LOCAL_BUILD=1
if [[ "$USE_GHCR" =~ ^[Yy] ]]; then
  echo
  echo "GHCR login: echo \$GITHUB_TOKEN | docker login ghcr.io -u USER --password-stdin"
  read -r -p "Pull GHCR image now? [y/N]: " DOPULL
  DOPULL=${DOPULL:-n}
  if [[ "$DOPULL" =~ ^[Yy] ]] && docker pull "$IMAGE"; then
    FORCE_BUILD=0
    set_env FORCE_LOCAL_BUILD 0
    export FORCE_LOCAL_BUILD=0
  else
    echo "Building locally."
  fi
fi

mkdir -p postgis/init data/valhalla data/pbf
chmod a+rx postgis postgis/init 2>/dev/null || true
chmod a+r postgis/init/*.sql 2>/dev/null || true
[[ -d data/valhalla/active.osm.pbf ]] && rm -rf data/valhalla/active.osm.pbf

# Valhalla tiles are built for the selected city/district when a level is ready
# (API prepare_valhalla_for_level). Do not seed active.osm.pbf from a full
# regional Geofabrik pack here — that tiles hundreds of MB for no reason.

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.host.yml --env-file .env)
"${COMPOSE[@]}" config --quiet
[[ "$FORCE_BUILD" == "1" ]] && "${COMPOSE[@]}" build api

SERVICES=(api postgis kismet)
# Only start Valhalla if a prior level already left a real active extract.
if [[ -f data/valhalla/active.osm.pbf && -s data/valhalla/active.osm.pbf ]]; then
  SERVICES+=(valhalla)
  echo "Valhalla: starting (existing active extract)"
else
  echo "Valhalla: skipped until a level is created"
fi
"${COMPOSE[@]}" up -d "${SERVICES[@]}"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "=== Setup done ==="
echo "UI:     http://${IP:-127.0.0.1}:1337/"
echo "Status: http://${IP:-127.0.0.1}:1337/status"
echo "Kismet: http://${IP:-127.0.0.1}:2501/  (Compose container; host kismet.service must stay off)"
echo "Later:  ./run.sh  — or preferred: DATA_ROOT=… docker compose up -d"
