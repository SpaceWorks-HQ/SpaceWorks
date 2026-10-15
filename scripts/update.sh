#!/usr/bin/env bash
# Apply the newest fully-published Space Works release to a production Compose stack.
set -euo pipefail

UPDATE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SPACEWORKS_UPDATE_INSTALL_DIR:-$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)}"
cd "$ROOT"
export SPACEWORKS_UPDATE_INSTALL_DIR="$ROOT"
source "$UPDATE_SCRIPT_DIR/install-owner.sh"
require_install_owner "$UPDATE_SCRIPT_DIR/update.sh" "$@"

COMPOSE=("$UPDATE_SCRIPT_DIR/spaceworks-compose.sh" bundled)
# The old wrapper/proofs are still authoritative until backup and bundle replacement.
if [[ "$UPDATE_SCRIPT_DIR" != "$ROOT/scripts" ]]; then
  COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
fi
source "$UPDATE_SCRIPT_DIR/compose-deployment.sh"
deployment_services
LOCK_DIR="$ROOT/.spaceworks-update.lock"
VERSION_FILE="$ROOT/.spaceworks-version"
source "$UPDATE_SCRIPT_DIR/spaceworks-repository.sh"
configure_release_repository
OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-$(repository_env_value SPACEWORKS_OPS_HOST_DIR)}"
OPS_DIR="${OPS_DIR:-/var/lib/spaceworks/ops}"
export SPACEWORKS_OPS_HOST_DIR="$OPS_DIR"
RELEASE_API="https://api.github.com/repos/$SPACEWORKS_REPOSITORY/releases?per_page=100"
update_complete=0
deployment_started=0
host_configuration_started=0
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
MODULE_AREAS=""
MODULE_CONFIRM_REMOVALS=0
NO_MODULE_CHANGES=0
REQUESTED_VERSION=""

say() { printf '[Space Works updater] %s\n' "$*"; }
warn() { printf '[Space Works updater] WARNING: %s\n' "$*" >&2; }
die() { printf '[Space Works updater] ERROR: %s\n' "$*" >&2; exit 1; }
source "$UPDATE_SCRIPT_DIR/update-lock.sh"
source "$UPDATE_SCRIPT_DIR/module-selection.sh"
source "$UPDATE_SCRIPT_DIR/cleanup-run-once.sh"
source "$UPDATE_SCRIPT_DIR/update-rollback.sh"

while (($# > 0)); do
  case "$1" in
    --force) ;;
    --version)
      [[ -z "$REQUESTED_VERSION" ]] || die "--version may only be specified once."
      shift; (($# > 0)) || die "--version requires an immutable main release version."
      REQUESTED_VERSION="$1"
      [[ "$REQUESTED_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]] \
        || die "--version requires X.Y.Z-main.<run>.<12 lowercase hex SHA>."
      ;;
    --modules) MODULE_REQUESTED=1; MODULE_MODE=interactive ;;
    --modules-only) MODULE_REQUESTED=1; MODULE_ONLY=1 ;;
    --no-module-changes) NO_MODULE_CHANGES=1 ;;
    --all-modules) MODULE_REQUESTED=1; MODULE_MODE=all ;;
    --areas=*) MODULE_REQUESTED=1; MODULE_MODE=areas; MODULE_AREAS="${1#*=}" ;;
    --without=*)
      MODULE_REQUESTED=1; MODULE_WITHOUT="${1#*=}"
      [[ "$MODULE_MODE" == all || "$MODULE_MODE" == areas ]] || MODULE_MODE=without
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
Usage: scripts/update.sh [--force] [--version <version>] [module options]
  --version <version>       deploy this exact published main release of the configured repository
  --modules                 interactively review current areas (on/partial/off)
  --modules-only            change modules without checking for a release
  --all-modules             enable every area and supported feature
  --areas=inventory,machines,...  select exactly these areas (empty = core and always-on only)
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
[[ "$MODULE_ONLY" == 0 || -z "$REQUESTED_VERSION" ]] \
  || die "--version cannot be combined with --modules-only."
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
    if ${COMPOSE[@]+"${COMPOSE[@]}"} exec -T "$APP_SERVICE" python -c \
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
  if [[ "$deployment_started" == 1 && "$update_complete" == 0 ]]; then
    rollback_application_images

  fi
  if [[ "$exit_code" != 0 && "$host_configuration_started" == 1 && "$deployment_started" == 0 ]]; then
    warn "Host configuration upgrade stopped before deployment; the database was not replaced."
    say "Restore host runtime files from ${HOST_CONFIG_BACKUP_DIR:-$ROOT/backups/host-config-*} if present, then run:"
    say "  bash '$ROOT/scripts/init-host-orchestration.sh'"
    say "Then retry bash scripts/update.sh --force --no-module-changes. Keep the database backup."
  fi
  release_update_lock
  exit "$exit_code"
}
trap cleanup EXIT
acquire_update_lock
source "$UPDATE_SCRIPT_DIR/retire-update-polling.sh"
retire_update_polling

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

# A pinned deployment checks its exact tag, including releases beyond the list's first page.
if [[ -n "$REQUESTED_VERSION" ]]; then
  RELEASE_API="https://api.github.com/repos/$SPACEWORKS_REPOSITORY/releases/tags/v$REQUESTED_VERSION"
fi
release_json="$(curl --fail --silent --show-error --location \
  --connect-timeout 10 --max-time 30 --retry 2 --retry-delay 5 \
  --header 'Accept: application/vnd.github+json' \
  --header 'User-Agent: spaceworks-self-host-updater' "$RELEASE_API")"
version="$(printf '%s' "$release_json" | "${COMPOSE[@]}" exec -T "$APP_SERVICE" \
  python -c "$(cat "$UPDATE_SCRIPT_DIR/select-main-release.py")" "$REQUESTED_VERSION" "$SPACEWORKS_REPOSITORY")" \
  || die "Could not validate an eligible published main release. Start the app, then retry."
version="$(printf '%s' "$version" | tr -d '\r\n')"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]] \
  || die "The updater requires an immutable published main release version."
current=""
[[ ! -f "$VERSION_FILE" ]] || current="$(tr -d '[:space:]' < "$VERSION_FILE")"
previous_version="$current"
if [[ "$current" == "$version" ]]; then
  say "$version is already installed."
  if [[ "$MODULE_REQUESTED" == 1 ]]; then change_modules; fi
  exit 0
fi

say "Updating ${current:-untracked installation} to $version."

mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
${COMPOSE[@]+"${COMPOSE[@]}"} up -d --wait db
backup_name="pre-update-$(date -u +%Y%m%dT%H%M%SZ)-$$.sql.gz"
say "Creating database backup backups/$backup_name."
# Restore can switch to a sibling DB; POSTGRES_DB still names the original bootstrap DB.
backup_database="$("${COMPOSE[@]}" exec -T "$APP_SERVICE" python -c \
  "import os, urllib.parse; print(urllib.parse.unquote(urllib.parse.urlsplit(os.environ['DATABASE_URL']).path.lstrip('/')))")"
backup_database="$(printf '%s' "$backup_database" | tr -d '\r\n')"
[[ "$backup_database" =~ ^[A-Za-z0-9_][A-Za-z0-9_-]{0,62}$ ]] \
  || die "The active database pointer has an invalid database name; update cancelled."
# Write the dump first: POSIX sh pipelines otherwise hide a failed pg_dump behind gzip.
"${COMPOSE[@]}" exec -T -e "SPACEWORKS_BACKUP_DATABASE=$backup_database" db sh -c \
  'set -e; raw="/backups/'"$backup_name"'.raw"; trap '\''rm -f "$raw"'\'' EXIT; pg_dump -U "$POSTGRES_USER" "$SPACEWORKS_BACKUP_DATABASE" > "$raw"; test -s "$raw"; gzip -c "$raw" > "/backups/'"$backup_name"'"' \
  || die "Database backup failed; update cancelled."
"${COMPOSE[@]}" exec -T db test -s "/backups/$backup_name" \
  || die "Database backup was not created; update cancelled."
export MAKERSPACE_IMAGE_TAG="$version"

# Check the new backend image exists before replacing any committed host configuration.
docker pull "$MAKERSPACE_BACKEND_IMAGE:$version"
host_configuration_started=1
source "$UPDATE_SCRIPT_DIR/retire-update-tombstone.sh"
retire_update_tombstone
source "$UPDATE_SCRIPT_DIR/install-host-bundle.sh"
install_staged_host_bundle "$(cd "$UPDATE_SCRIPT_DIR/.." && pwd)"
# Keep future runner and manual runs on the same configured repository.
if [[ -f "$ROOT/.env" ]]; then
  repository_file="$(mktemp "$ROOT/.deploy-env.XXXXXX")"
  sed '/^SPACEWORKS_REPOSITORY=/d' "$ROOT/.env" > "$repository_file"
  printf '\nSPACEWORKS_REPOSITORY=%s\n' "$SPACEWORKS_REPOSITORY" >> "$repository_file"
  chmod 600 "$repository_file"
  mv -f -- "$repository_file" "$ROOT/.env"
fi
# Pin the newly installed wrapper and record its new compose hashes before using it.
# The direct Docker pull above did not depend on the still-old digest records.
HOST_CONFIG_IMAGE="$MAKERSPACE_BACKEND_IMAGE:$version"
OPS_HOST_DIR="$OPS_DIR"
source "$UPDATE_SCRIPT_DIR/setup-host-orchestration.sh"
refresh_compose_config
COMPOSE=("$UPDATE_SCRIPT_DIR/spaceworks-compose.sh" bundled)
say "Pulling immutable release images."
${COMPOSE[@]+"${COMPOSE[@]}"} pull ${IMAGE_SERVICES[@]+"${IMAGE_SERVICES[@]}"}

# Refresh the producer proof for the new migration tree before any new workers start.
HOST_CONFIG_IMAGE="$MAKERSPACE_BACKEND_IMAGE:$version"
source "$UPDATE_SCRIPT_DIR/setup-host-orchestration.sh"
install_producer_capability
say "Running migrations and replacing application containers."
deployment_started=1
${COMPOSE[@]+"${COMPOSE[@]}"} up -d --remove-orphans

wait_for_backend || die "Release $version did not become ready. The backup is backups/$backup_name."

printf '%s\n' "$version" > "$VERSION_FILE"
update_complete=1
cleanup_run_once_jobs || warn "Could not remove finished start-up jobs."
find "$ROOT/backups" -maxdepth 1 -type f -name 'pre-update-*.sql.gz' -mtime +14 -delete
say "Release update complete: $version."
if [[ "$MODULE_REQUESTED" == 1 ]]; then
  change_modules || die "Release $version is healthy, but one or more module changes were not applied."
fi
say "Update complete: $version."
