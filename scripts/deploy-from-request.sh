#!/usr/bin/env bash
# A signed delivery is only a wake-up signal. update.sh rechecks GitHub itself.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/install-owner.sh"
require_install_owner "$ROOT/scripts/deploy-from-request.sh" "$@"
source "$ROOT/scripts/spaceworks-repository.sh"
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-$(repository_env_value SPACEWORKS_OPS_HOST_DIR)}"
OPS_DIR="${OPS_DIR:-/var/lib/spaceworks/ops}"
REQUEST_DIR="${SPACEWORKS_DEPLOY_REQUEST_DIR:-$OPS_DIR/deploy-requests}"
[[ -d "$REQUEST_DIR" ]] || exit 0
LOCK_DIR="$ROOT/.spaceworks-deploy.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  owner=""
  owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"; owner="${owner//[[:space:]]/}"
  if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || exit 0
    mkdir "$LOCK_DIR" 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
trap 'rm -f "$LOCK_DIR/pid"; rmdir "$LOCK_DIR"' EXIT
shopt -s nullglob
requests=("$REQUEST_DIR"/*.json)
((${#requests[@]})) || exit 0
# Keep the batch until the updater has waited for existing host operations. A crash
# before it starts leaves the requests queued; arrivals during the run remain separate.
mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
status=75
while [[ "$status" == 75 ]]; do
  status=0
  SPACEWORKS_DEPLOY_WAIT=1 bash "$ROOT/scripts/update.sh" --force --no-module-changes \
    >> "$ROOT/backups/deploy.log" 2>&1 || status=$?
  [[ "$status" != 75 ]] || sleep 10
done
rm -f -- "${requests[@]}"
exit "$status"
