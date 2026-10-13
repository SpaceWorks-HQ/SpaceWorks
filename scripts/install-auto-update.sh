#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/install-owner.sh"
require_install_owner "$ROOT/scripts/install-auto-update.sh" "$@"
case "$ROOT" in
  *"'"*|*$'\n'*) printf 'ERROR: the install path cannot contain single quotes or newlines.\n' >&2; exit 1 ;;
esac
command -v crontab >/dev/null 2>&1 || {
  printf 'ERROR: crontab is unavailable. Install your distribution cron package and enable its service, then rerun bash %q. Alternatively schedule bash %q every seven days as %s.\n' "$0" "$ROOT/scripts/update.sh" "$(id -un)" >&2
  exit 1
}

COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)

MARKER="# Space Works automatic production update"
JOB="0 3 * * 0 PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; cd '$ROOT' && bash '$ROOT/scripts/update.sh' >> '$ROOT/backups/auto-update.log' 2>&1"
existing="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$existing" | grep -v -F "$MARKER" | grep -v -F "$ROOT/scripts/update.sh" || true)"

mkdir -p "$ROOT/backups"
{
  printf '%s\n' "$filtered"
  printf '%s\n' "$MARKER"
  printf '%s\n' "$JOB"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -
${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management python manage.py update_control set-auto on >/dev/null

printf 'Automatic Space Works updates check the newest main release every seven days in %s\x27s crontab.\n' "$(id -un)"
