#!/usr/bin/env bash
# Apply the newest fully-published Space Works release to a production Compose stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
mkdir -p "$OPS_DIR"
exec 8>"$OPS_DIR/operation.lock"
flock -n 8 || { printf '[Space Works updater] Another deployment operation is running; skipping.\n'; exit 0; }

COMPOSE=(docker compose -f docker-compose.prod.yml)
LOCK_DIR="$ROOT/.spaceworks-update.lock"
VERSION_FILE="$ROOT/.spaceworks-version"
RELEASE_API="https://api.github.com/repos/SpaceWorks-HQ/SpaceWorks/releases/latest"
update_claimed=0
update_complete=0
deployment_started=0
previous_version=""

say() { printf '[Space Works updater] %s\n' "$*"; }
die() { printf '[Space Works updater] ERROR: %s\n' "$*" >&2; exit 1; }
wait_for_backend() {
  local attempt
  for attempt in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T backend python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3).read()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}
force_arg=()
if [[ "${1:-}" == "--force" ]]; then
  force_arg=(--force)
elif [[ -n "${1:-}" ]]; then
  die "Unknown option: $1"
fi

command -v docker >/dev/null 2>&1 || die "Docker is not installed."
command -v curl >/dev/null 2>&1 || die "curl is required to check GitHub releases."

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  sleep 1
  lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$lock_pid" =~ ^[0-9]+$ ]] && kill -0 "$lock_pid" 2>/dev/null; then
    say "Another update is already running; skipping."
    exit 0
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || die "Could not clear a stale update lock."
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"
cleanup() {
  exit_code=$?
  trap - EXIT
  set +e
  if [[ "$update_claimed" == 1 && "$update_complete" == 0 ]]; then
    failure_message="Host update failed. Check backups/auto-update.log."
    if [[ "$deployment_started" == 1 && \
      "$previous_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]]; then
      say "Update failed; rolling application containers back to $previous_version."
      export MAKERSPACE_IMAGE_TAG="$previous_version"
      "${COMPOSE[@]}" pull migrate backend worker beat frontend || \
        say "Could not refresh previous images; trying the host's cached copies."
      if "${COMPOSE[@]}" up -d && wait_for_backend; then
        say "Rollback complete: $previous_version is healthy."
        failure_message="Update failed; application containers rolled back to $previous_version. The database backup was retained."
      else
        say "ERROR: automatic rollback to $previous_version failed."
        failure_message="Update and automatic rollback failed. Restore the database backup and previous image tag manually."
      fi
    fi
    "${COMPOSE[@]}" exec -T backend python manage.py update_control fail \
      --message "$failure_message" >/dev/null 2>&1 || true
  fi
  rm -f "$LOCK_DIR/pid"
  rmdir "$LOCK_DIR" 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT

release_json="$(curl --fail --silent --show-error --location \
  --header 'Accept: application/vnd.github+json' \
  --header 'User-Agent: spaceworks-self-host-updater' \
  "$RELEASE_API")"
tag="$(printf '%s' "$release_json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
version="${tag#v}"

if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]]; then
  die "GitHub latest release returned an unexpected tag: ${tag:-<empty>}"
fi

current=""
if [[ -f "$VERSION_FILE" ]]; then
  current="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi
previous_version="$current"

decision="$("${COMPOSE[@]}" exec -T backend python manage.py update_control claim \
  --current="$current" --available="$version" "${force_arg[@]}")" \
  || die "The running Space Works backend could not accept the update check."
decision="$(printf '%s\n' "$decision" | tr -d '\r' | tail -n 1)"
if [[ "$decision" != "run" ]]; then
  if [[ "$current" == "$version" ]]; then
    say "$version is already installed."
  else
    say "$version is available; automatic updates are off and no manual update is queued."
  fi
  exit 0
fi
update_claimed=1

say "Updating ${current:-untracked installation} to $version."
export MAKERSPACE_IMAGE_TAG="$version"

mkdir -p "$ROOT/backups"
"${COMPOSE[@]}" up -d --wait db
backup_name="pre-update-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
say "Creating database backup backups/$backup_name."
"${COMPOSE[@]}" exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip -c > "/backups/'"$backup_name"'"'
"${COMPOSE[@]}" exec -T db test -s "/backups/$backup_name" \
  || die "Database backup was not created; update cancelled."
"${COMPOSE[@]}" exec -T backend python manage.py update_control record-backup \
  --name "$backup_name" >/dev/null

say "Pulling immutable release images."
"${COMPOSE[@]}" pull migrate backend worker beat frontend

say "Running migrations and replacing application containers."
deployment_started=1
"${COMPOSE[@]}" up -d

wait_for_backend || die "Release $version did not become ready. The backup is backups/$backup_name."

printf '%s\n' "$version" > "$VERSION_FILE"
"${COMPOSE[@]}" exec -T backend python manage.py update_control complete \
  --version "$version" >/dev/null
update_complete=1
find "$ROOT/backups" -maxdepth 1 -type f -name 'pre-update-*.sql.gz' -mtime +14 -delete
say "Update complete: $version."
