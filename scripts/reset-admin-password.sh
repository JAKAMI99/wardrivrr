#!/usr/bin/env bash
# Reset the wardrivrr admin password via the API container (or local Python).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASSWORD="${1:-}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.host.yml)

usage() {
  cat <<'EOF'
Usage:
  ./scripts/reset-admin-password.sh [password]

Docker (default when the API container is running):
  ./scripts/reset-admin-password.sh 'YourNewPassword'
  # or interactive prompt:
  ./scripts/reset-admin-password.sh

Local (host API / debug, PostGIS reachable):
  WARDRIVRR_RESET_LOCAL=1 ./scripts/reset-admin-password.sh 'YourNewPassword'
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -n "${WARDRIVRR_RESET_LOCAL:-}" ]]; then
  if [[ -n "$PASSWORD" ]]; then
    exec python "$ROOT/scripts/reset_admin_password.py" "$PASSWORD"
  fi
  exec python "$ROOT/scripts/reset_admin_password.py"
fi

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx 'wardrivrr_api'; then
  echo "Container wardrivrr_api is not running." >&2
  echo "Start the stack, or use: WARDRIVRR_RESET_LOCAL=1 $0 ..." >&2
  exit 1
fi

if [[ -n "$PASSWORD" ]]; then
  "${COMPOSE[@]}" exec -T api python /app/scripts/reset_admin_password.py "$PASSWORD"
else
  "${COMPOSE[@]}" exec -it api python /app/scripts/reset_admin_password.py
fi
