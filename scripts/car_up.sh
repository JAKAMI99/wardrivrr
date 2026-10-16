#!/usr/bin/env bash
# Subsequent boots: local build by default (FORCE_LOCAL_BUILD=1). Optional GHCR pull.
# gpsd stays on host.
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

if [[ ! -s deploy/kismet/kismet_site.conf ]]; then
  echo "Missing deploy/kismet/kismet_site.conf — run ./scripts/car_setup.sh first."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Cannot talk to Docker (permission denied on /var/run/docker.sock)."
  echo "  sudo usermod -aG docker \"\$USER\" && newgrp docker"
  exit 1
fi

IMAGE="${WARDRIVRR_IMAGE:-wardrivrr-api:local}"
if [[ "$IMAGE" == *"/OWNER/"* ]] || [[ "$IMAGE" == *"/owner/"* ]]; then
  echo "WARDRIVRR_IMAGE still contains the OWNER placeholder: $IMAGE"
  echo "Run ./scripts/car_setup.sh or set WARDRIVRR_IMAGE=wardrivrr-api:local in .env."
  exit 1
fi
export WARDRIVRR_IMAGE="$IMAGE"
# Default local unless .env explicitly sets FORCE_LOCAL_BUILD=0 for GHCR-only boots
FORCE_LOCAL_BUILD="${FORCE_LOCAL_BUILD:-1}"

echo "=== wardrivrr car_up ==="
echo "Image: $WARDRIVRR_IMAGE"
echo "FORCE_LOCAL_BUILD=$FORCE_LOCAL_BUILD"
echo "Host architecture: $(uname -m)"

# Host gpsd
if systemctl is-active --quiet gpsd 2>/dev/null || pgrep -x gpsd >/dev/null 2>&1; then
  echo "gpsd: running"
else
  echo "gpsd: NOT running — starting…"
  sudo systemctl start gpsd 2>/dev/null || sudo service gpsd start 2>/dev/null || true
fi

# Host Kismet (not a Docker service by default)
mkdir -p data/kismet_logs
if [[ -s /etc/kismet/kismet_site.conf ]] || [[ -s deploy/kismet/kismet_site.conf ]]; then
  if [[ -f deploy/kismet/kismet_site.conf ]]; then
    sudo mkdir -p /etc/kismet
    sudo cp -f deploy/kismet/kismet_site.conf /etc/kismet/kismet_site.conf 2>/dev/null || true
  fi
  if systemctl list-unit-files wardrivrr-kismet.service >/dev/null 2>&1; then
    if systemctl is-active --quiet wardrivrr-kismet; then
      echo "kismet: wardrivrr-kismet running"
    else
      echo "kismet: starting wardrivrr-kismet…"
      sudo systemctl start wardrivrr-kismet 2>/dev/null || true
    fi
  elif command -v kismet >/dev/null 2>&1; then
    if pgrep -x kismet >/dev/null 2>&1; then
      echo "kismet: process running"
    else
      echo "kismet: no systemd unit — start manually: kismet --no-ncurses &"
    fi
  else
    echo "kismet: not installed (host apt). Stack continues without RF until you install it."
  fi
fi

# Ensure PostGIS can read ./postgis/init on first volume create
chmod a+rx postgis postgis/init 2>/dev/null || true
chmod a+r postgis/init/*.sql 2>/dev/null || true

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env)
"${COMPOSE[@]}" config --quiet
mkdir -p data

PULLED=0
if [[ "$FORCE_LOCAL_BUILD" != "1" ]]; then
  if docker pull "$WARDRIVRR_IMAGE"; then
    echo "Using GHCR image (GitHub Actions build)."
    PULLED=1
  else
    echo "GHCR pull failed — local build fallback."
  fi
fi

if [[ "$PULLED" != "1" ]]; then
  echo "Building API image locally…"
  "${COMPOSE[@]}" build api
fi

"${COMPOSE[@]}" up -d

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "API: http://${IP:-127.0.0.1}:8000/"
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
echo "Tip: cgps -s  |  docker compose -f docker-compose.yml -f deploy/compose.car.yml ps"
