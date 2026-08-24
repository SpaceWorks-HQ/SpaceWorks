#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "$ROOT" in
  *"'"*) printf 'ERROR: the install path cannot contain a single quote.\n' >&2; exit 1 ;;
esac
command -v crontab >/dev/null 2>&1 || {
  printf 'ERROR: crontab is unavailable; schedule scripts/update.sh every seven days with your service manager.\n' >&2
  exit 1
}

COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
"${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control set-auto on >/dev/null

MARKER="# Space Works automatic production update"
JOB="0 3 * * 0 cd '$ROOT' && bash '$ROOT/scripts/update.sh' >> '$ROOT/backups/auto-update.log' 2>&1"
existing="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$existing" | grep -v -F "$MARKER" | grep -v -F "$ROOT/scripts/update.sh" || true)"

mkdir -p "$ROOT/backups"
{
  printf '%s\n' "$filtered"
  printf '%s\n' "$MARKER"
  printf '%s\n' "$JOB"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

printf 'Automatic Space Works updates are enabled and checked every seven days.\n'
