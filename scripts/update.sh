#!/usr/bin/env bash
# Apply the newest fully-published Space Works release to a production Compose stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
LOCK_DIR="$ROOT/.spaceworks-update.lock"
VERSION_FILE="$ROOT/.spaceworks-version"
RELEASE_API="https://api.github.com/repos/SpaceWorks-HQ/SpaceWorks/releases/latest"
update_claimed=0
update_complete=0
deployment_started=0
previous_version=""
UPDATE_LOCK_HELD=0
UPDATE_LOCK_OVERRIDE=0
MODULE_REQUESTED=0
MODULE_ONLY=0
MODULE_MODE=interactive
MODULE_INTERACTIVE=0
MODULE_MAKERSPACE=""
MODULE_ALL_MAKERSPACES=0
MODULE_WITHOUT=""
MODULE_CONFIRM_REMOVALS=0
NO_MODULE_CHANGES=0

say() { printf '[Space Works updater] %s\n' "$*"; }
warn() { printf '[Space Works updater] WARNING: %s\n' "$*" >&2; }
die() { printf '[Space Works updater] ERROR: %s\n' "$*" >&2; exit 1; }
source "$ROOT/scripts/update-lock.sh"
source "$ROOT/scripts/module-selection.sh"

force_arg=()
while (($# > 0)); do
  case "$1" in
    --force) force_arg=(--force) ;;
    --modules) MODULE_REQUESTED=1; MODULE_MODE=interactive ;;
    --modules-only) MODULE_REQUESTED=1; MODULE_ONLY=1 ;;
    --no-module-changes) NO_MODULE_CHANGES=1 ;;
    --all-modules) MODULE_REQUESTED=1; MODULE_MODE=all ;;
    --without=*)
      MODULE_REQUESTED=1; MODULE_WITHOUT="${1#*=}"
      [[ "$MODULE_MODE" == all ]] || MODULE_MODE=without
      ;;
    --makerspace)
      shift; (($# > 0)) || die "--makerspace requires a slug."
      MODULE_MAKERSPACE="$1"; MODULE_REQUESTED=1
      ;;
    --all-makerspaces) MODULE_ALL_MAKERSPACES=1; MODULE_REQUESTED=1 ;;
    --confirm-removals) MODULE_CONFIRM_REMOVALS=1 ;;
    --override-lock) UPDATE_LOCK_OVERRIDE=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/update.sh [--force] [module options]
  --modules                 interactively review current modules
  --modules-only            change modules without checking for a release
  --all-modules             enable every optional module
  --without=key1,key2       keep current state, or all modules, except these keys
  --makerspace <slug>       target one makerspace
  --all-makerspaces         explicitly target every makerspace
  --confirm-removals        acknowledge retained-data module removals non-interactively
  --no-module-changes       update images only
  --override-lock           clear a verified stale/wedged portable update lock
EOF
      exit 0
      ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done
[[ "$MODULE_ALL_MAKERSPACES" == 0 || -z "$MODULE_MAKERSPACE" ]] \
  || die "Use either --makerspace or --all-makerspaces, not both."
[[ "$NO_MODULE_CHANGES" == 0 || "$MODULE_REQUESTED" == 0 ]] \
  || die "--no-module-changes cannot be combined with module-selection options."
if [[ "$MODULE_REQUESTED" == 0 && "$NO_MODULE_CHANGES" == 0 && -t 0 && -t 1 ]]; then
  MODULE_REQUESTED=1
  MODULE_MODE=interactive
fi
if [[ "$MODULE_MODE" == interactive ]]; then
  [[ "$MODULE_REQUESTED" == 0 || ( -t 0 && -t 1 ) ]] \
    || die "Interactive module selection needs a terminal; use --all-modules/--without or --no-module-changes."
  MODULE_INTERACTIVE="$MODULE_REQUESTED"
fi

wait_for_backend() {
  local _
  for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T backend python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3).read()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 3
  done
  return 1
}

command -v docker >/dev/null 2>&1 || die "Docker is not installed."
command -v curl >/dev/null 2>&1 || die "curl is required to check GitHub releases."
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
    "${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control fail \
      --message "$failure_message" >/dev/null 2>&1 || true
  fi
  release_update_lock
  exit "$exit_code"
}
trap cleanup EXIT
acquire_update_lock

if [[ "$MODULE_REQUESTED" == 1 ]]; then
  module_targets || die "Module targeting failed; no release or module changes were made."
  if [[ "$MODULE_ALL_MAKERSPACES" == 0 ]]; then
    MODULE_MAKERSPACE="${MODULE_TARGETS[0]}"
  fi
fi
if [[ "$MODULE_ONLY" == 1 ]]; then
  change_modules || die "One or more requested module changes were not applied."
  say "Module review complete."
  exit 0
fi

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

decision="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control claim \
  --current="$current" --available="$version" "${force_arg[@]}")" \
  || die "The running Space Works backend could not accept the update check."
decision="$(printf '%s\n' "$decision" | tr -d '\r' | tail -n 1)"
if [[ "$decision" != "run" ]]; then
  if [[ "$current" == "$version" ]]; then
    say "$version is already installed."
  else
    say "$version is available; automatic updates are off and no manual update is queued."
  fi
  if [[ "$MODULE_REQUESTED" == 1 ]]; then
    change_modules || die "One or more requested module changes were not applied."
    say "Module review complete."
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
"${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control record-backup \
  --name "$backup_name" >/dev/null

say "Pulling immutable release images."
"${COMPOSE[@]}" pull migrate backend worker beat frontend

say "Running migrations and replacing application containers."
deployment_started=1
"${COMPOSE[@]}" up -d

wait_for_backend || die "Release $version did not become ready. The backup is backups/$backup_name."

printf '%s\n' "$version" > "$VERSION_FILE"
"${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control complete \
  --version "$version" >/dev/null
update_complete=1
find "$ROOT/backups" -maxdepth 1 -type f -name 'pre-update-*.sql.gz' -mtime +14 -delete
say "Release update complete: $version."
if [[ "$MODULE_REQUESTED" == 1 ]]; then
  change_modules || die "Release $version is healthy, but one or more module changes were not applied."
fi
say "Update complete: $version."
