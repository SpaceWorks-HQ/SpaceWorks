#!/usr/bin/env bash
# Root child of the owner-run updater; its parent retains the portable update lock.
set -euo pipefail
UPDATE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SPACEWORKS_UPDATE_INSTALL_DIR:-$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)}"
cd "$ROOT"
export SPACEWORKS_UPDATE_INSTALL_DIR="$ROOT"
[[ "$(id -u)" == 0 ]] || { echo "Run this rollback helper through scripts/update.sh (sudo is required)." >&2; exit 1; }
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
VERSION_FILE="$ROOT/.spaceworks-version"
COMPOSE=("$UPDATE_SCRIPT_DIR/spaceworks-compose.sh" bundled)
APP_SERVICE=backend
HOST_ROLLBACK_PLAN="${1:-resume}"
say() { printf '[Space Works rollback] %s\n' "$*"; }
die() { printf '[Space Works rollback] ERROR: %s\n' "$*" >&2; exit 1; }
source "$UPDATE_SCRIPT_DIR/update-rollback.sh"
layer="${SPACEWORKS_COMPOSE_LAYER:-}"
if [[ -z "$layer" && -f "$ROOT/.spaceworks-layer" ]]; then
  layer="$(tr -d '[:space:]' < "$ROOT/.spaceworks-layer")"
fi
[[ "$layer" != single ]] || die "The existing restore supervisor requires the bundled topology."
wait_for_backend() {
  local attempt
  for attempt in $(seq 1 60); do
    if ${COMPOSE[@]+"${COMPOSE[@]}"} exec -T backend python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3).read()" \
      >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  return 1
}
command -v flock >/dev/null 2>&1 || die "Rollback requires flock."
exec 8>"$OPS_DIR/operation.lock"
flock -n 8 || die "Another host operation started before the rollback handoff."
handle_update_rollback
