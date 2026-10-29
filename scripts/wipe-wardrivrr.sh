#!/usr/bin/env bash
# Nuclear wipe of wardrivrr on this host — nothing left for a real redeploy.
# Install / refresh copy in home:
#   cp scripts/wipe-wardrivrr.sh ~/wipe-wardrivrr.sh && chmod +x ~/wipe-wardrivrr.sh
#
# Usage:
#   ~/wipe-wardrivrr.sh              # interactive confirm
#   ~/wipe-wardrivrr.sh --yes        # no prompt
#   ~/wipe-wardrivrr.sh --yes --keep-images
#
# After this: git clone … wardrivrr && cd wardrivrr && ./deploy.sh
set -euo pipefail

YES=0
KEEP_IMAGES=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) YES=1 ;;
    --keep-images) KEEP_IMAGES=1 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
  esac
done

HOME_DIR="${HOME:-}"
if [[ -z "$HOME_DIR" ]]; then
  HOME_DIR="$(getent passwd "$(id -un)" 2>/dev/null | cut -d: -f6 || true)"
fi
if [[ -z "$HOME_DIR" || ! -d "$HOME_DIR" ]]; then
  echo "ERROR: cannot resolve HOME for wipe candidates." >&2
  exit 1
fi
# Every place a checkout / nested clone / orphan data might live
CANDIDATE_ROOTS=(
  "$HOME_DIR/wardrivrr"
  "$HOME_DIR/wardrivrr/wardrivrr"
  "$HOME_DIR/code/wardrivrr"
  "$HOME_DIR/src/wardrivrr"
)

echo "=== wipe wardrivrr (full reinstall) ==="
echo "Host: $(whoami)@$(hostname)"
echo "This removes:"
echo "  - systemd units wardrivrr-stack / wardrivrr-kismet"
echo "  - ALL docker containers/volumes/networks named wardrivrr*"
echo "  - Valhalla / PostGIS / API images used by the stack (unless --keep-images)"
echo "  - ALL checkouts and nested clones under ~ (and their data/ .env)"
echo "  - leftover ~/wipe artifacts under data/valhalla tiles, pbf, users, pg"
echo
echo "Keeps: gpsd, host Kismet package, this wipe script itself."
echo

if [[ "$YES" -ne 1 ]]; then
  read -r -p "Type YES to destroy wardrivrr completely: " ans
  [[ "$ans" == "YES" ]] || { echo "Aborted."; exit 1; }
fi

# Collect existing roots (including nested) before deleting
ROOTS=()
for r in "${CANDIDATE_ROOTS[@]}"; do
  if [[ -d "$r" ]]; then
    ROOTS+=("$r")
  fi
done
# Also catch any other ~/wardrivrr* dirs
while IFS= read -r d; do
  [[ -z "$d" ]] && continue
  skip=0
  for e in "${ROOTS[@]+"${ROOTS[@]}"}"; do
    [[ "$d" == "$e" ]] && skip=1 && break
  done
  [[ "$skip" -eq 0 ]] && ROOTS+=("$d")
done < <(find "$HOME_DIR" -maxdepth 3 -type d -name 'wardrivrr' 2>/dev/null || true)

echo "[1/7] systemd"
for unit in wardrivrr-stack.service wardrivrr-kismet.service; do
  sudo systemctl disable --now "$unit" 2>/dev/null || true
  sudo rm -f "/etc/systemd/system/$unit" 2>/dev/null || true
done
sudo systemctl daemon-reload 2>/dev/null || true

echo "[2/7] compose down (every checkout)"
for root in "${ROOTS[@]+"${ROOTS[@]}"}"; do
  [[ -d "$root" ]] || continue
  echo "  → $root"
  (
    cd "$root" || exit 0
    if [[ -f docker-compose.yml ]]; then
      COMPOSE=(docker compose --project-directory "$root" -f docker-compose.yml)
      [[ -f deploy/compose.host.yml ]] && COMPOSE+=(-f deploy/compose.host.yml)
      [[ -f .env ]] && COMPOSE+=(--env-file .env)
      "${COMPOSE[@]}" down -v --remove-orphans 2>/dev/null || true
    fi
  )
done

echo "[3/7] containers / networks"
docker ps -aq --filter "name=wardrivrr" 2>/dev/null | xargs -r docker rm -f 2>/dev/null || true
# Named leftovers
for c in wardrivrr_api wardrivrr_postgis wardrivrr_valhalla wardrivrr_kismet; do
  docker rm -f "$c" 2>/dev/null || true
done
docker network ls -q --filter "name=wardrivrr" 2>/dev/null | xargs -r docker network rm 2>/dev/null || true

echo "[4/7] volumes"
docker volume ls -q 2>/dev/null | grep -E 'wardrivrr' | xargs -r docker volume rm -f 2>/dev/null || true
for v in wardrivrr_pgdata wardrivrr_valhalla_data wardrivrr_kismet_logs; do
  docker volume rm -f "$v" 2>/dev/null || true
done

echo "[5/7] images"
if [[ "$KEEP_IMAGES" -eq 0 ]]; then
  docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' 2>/dev/null | while read -r ref id; do
    case "$ref" in
      wardrivrr-api:*|wardrivrr:*|*wardrivrr*)
        docker rmi -f "$id" 2>/dev/null || true
        ;;
      ghcr.io/*/wardrivrr:*|ghcr.io/*/wardrivrr@*)
        docker rmi -f "$id" 2>/dev/null || true
        ;;
      postgis/postgis:*|ghcr.io/gis-ops/docker-valhalla/valhalla:*)
        docker rmi -f "$id" 2>/dev/null || true
        ;;
    esac
  done
  docker image prune -f >/dev/null 2>&1 || true
else
  echo "  (skipped --keep-images)"
fi

echo "[6/7] delete checkouts + any nested tree"
# Deepest paths first so nested dies before parent
IFS=$'\n' sorted=($(printf '%s\n' "${ROOTS[@]+"${ROOTS[@]}"}" | awk '{print length, $0}' | sort -nr | cut -d' ' -f2-))
for root in "${sorted[@]+"${sorted[@]}"}"; do
  [[ -d "$root" ]] || continue
  echo "  deleting $root"
  # Explicitly nuke Valhalla leftovers even if rm -rf races
  sudo rm -rf \
    "$root/data/valhalla" \
    "$root/data/pbf" \
    "$root/data/users" \
    "$root/data/cities" \
    "$root/.env" \
    2>/dev/null || true
  sudo rm -rf "$root"
done
# Orphan home leftovers from botched wipes
sudo rm -rf \
  "$HOME_DIR/wardrivrr" \
  "$HOME_DIR/.wardrivrr" \
  2>/dev/null || true

echo "[7/7] verify"
left_c=$(docker ps -aq --filter name=wardrivrr 2>/dev/null | wc -l | tr -d ' ')
left_v=$(docker volume ls -q 2>/dev/null | grep -cE 'wardrivrr' || true)
left_d=0
[[ -e "$HOME_DIR/wardrivrr" ]] && left_d=1

echo
echo "=== wipe done ==="
echo "Containers left: $left_c"
echo "Volumes left:    $left_v"
echo "Checkout left:   $left_d (0 = clean)"
echo
echo "Full reinstall:"
echo "  cd ~"
echo "  git clone https://github.com/JAKAMI99/wardrivrr.git wardrivrr"
echo "  cd ~/wardrivrr"
echo "  git checkout main && git pull"
echo "  ./deploy.sh"
echo
echo "Do NOT nest a second clone inside ~/wardrivrr."
echo "Valhalla will only start after you generate a city in Drive (no leftover PBF)."
