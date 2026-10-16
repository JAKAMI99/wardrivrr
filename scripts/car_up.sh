#!/usr/bin/env bash
# Subsequent boots: prefer GHCR pull, then compose up. gpsd stays on host.
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

IMAGE="${WARDRIVRR_IMAGE:-}"
if [[ -z "$IMAGE" ]]; then
  REMOTE="$(git remote get-url origin 2>/dev/null || true)"
  OWNER="$(printf '%s' "$REMOTE" | sed -nE 's#.*github\.com[:/]([^/]+)/.*#\1#p' | tr '[:upper:]' '[:lower:]')"
  if [[ -z "$OWNER" ]]; then
    echo "WARDRIVRR_IMAGE is unset and no GitHub owner could be read from origin."
    echo "Set WARDRIVRR_IMAGE=ghcr.io/<owner>/wardrivrr:latest in .env."
    exit 1
  fi
  IMAGE="ghcr.io/${OWNER}/wardrivrr:latest"
fi
if [[ "$IMAGE" == *"/OWNER/"* ]] || [[ "$IMAGE" == *"/owner/"* ]]; then
  echo "WARDRIVRR_IMAGE still contains the OWNER placeholder: $IMAGE"
  echo "Run ./scripts/car_setup.sh or fix WARDRIVRR_IMAGE in .env."
  exit 1
fi
export WARDRIVRR_IMAGE="$IMAGE"

echo "=== wardrivrr car_up ==="
echo "Image: $WARDRIVRR_IMAGE"
echo "Host architecture: $(uname -m)"

# Host gpsd
if systemctl is-active --quiet gpsd 2>/dev/null || pgrep -x gpsd >/dev/null 2>&1; then
  echo "gpsd: running"
else
  echo "gpsd: NOT running — starting…"
  sudo systemctl start gpsd 2>/dev/null || sudo service gpsd start 2>/dev/null || true
fi

COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.car.yml --env-file .env)
"${COMPOSE[@]}" config --quiet
mkdir -p data

PULLED=0
if [[ "${FORCE_LOCAL_BUILD:-0}" != "1" ]]; then
  if docker pull "$WARDRIVRR_IMAGE"; then
    echo "Using GHCR image (GitHub Actions build)."
    PULLED=1
  else
    echo "GHCR pull failed — local build fallback."
    echo "For a private package, login with a classic PAT that has read:packages:"
    echo "  echo \$GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USER --password-stdin"
  fi
fi

if [[ "$PULLED" != "1" ]] || [[ "${FORCE_LOCAL_BUILD:-0}" == "1" ]]; then
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
