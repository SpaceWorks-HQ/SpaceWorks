#!/usr/bin/env bash
# Space Works - guided first-run setup (Linux, macOS, or Windows Git Bash/WSL).
# Run it from the project folder:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$PWD"
source "$ROOT/scripts/install-owner.sh"
require_install_owner "$ROOT/setup.sh" "$@"
COMPOSE=("$ROOT/scripts/spaceworks-compose.sh" bundled)
BUILD_FROM_SOURCE=0
case "${1:-}" in
  "") ;;
  --build) BUILD_FROM_SOURCE=1 ;;
  *) printf 'Usage: bash setup.sh [--build]\n' >&2; exit 64 ;;
esac
if [[ "$BUILD_FROM_SOURCE" == 1 ]]; then
  export SPACEWORKS_COMPOSE_BUILD_LAYER=1
  export SPACEWORKS_HOST_CONFIG_BUILD=1
  HOST_CONFIG_IMAGE="spaceworks-host-configure:local"
else
  unset SPACEWORKS_COMPOSE_BUILD_LAYER
  export SPACEWORKS_HOST_CONFIG_BUILD=0
  HOST_CONFIG_IMAGE="${MAKERSPACE_BACKEND_IMAGE:-ghcr.io/spaceworks-hq/spaceworks-backend}:${MAKERSPACE_IMAGE_TAG:-latest}"
fi

say()  { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Keeps the installer below the repository's file-size ceiling while sharing no
# ambient database pointer values with the privileged configuration helper.
source "$ROOT/scripts/setup-host-orchestration.sh"
source "$ROOT/scripts/spaceworks-repository.sh"
source "$ROOT/scripts/cleanup-run-once.sh"

# Questionnaire precedes Docker checks, image pulls and writes to the checkout.
source "$ROOT/scripts/setup-questions.sh"
if [[ "${ANSWERS_CONFIRMED:-}" == yes ]]; then
  : # Confirmed answers inherited by native Windows through process environment.
elif [[ -f .spaceworks-answers ]]; then
  load_setup_answers "$ROOT/.spaceworks-answers" || die 'Invalid private answers file.'
elif [[ ! -f .env ]]; then
  ask_setup_questions || exit 0
  persist_setup_answers "$ROOT/.spaceworks-answers"
fi

# 1. Docker must be installed and running.
command -v docker >/dev/null 2>&1 || die "Docker is missing. On Linux, run install.sh to install it; on macOS/Windows, install Docker Desktop."
docker info >/dev/null 2>&1 || die "Docker is inaccessible. On Linux, run sudo systemctl start docker and sudo usermod -aG docker \$(id -un), then sign out and back in. On macOS/Windows, start Docker Desktop."
docker compose version >/dev/null 2>&1 || die "The 'docker compose' plugin is missing. Update Docker Desktop."

source "$ROOT/scripts/setup-first-run.sh"
source "$ROOT/scripts/retire-update-tombstone.sh"
retire_update_tombstone
source "$ROOT/scripts/retire-update-polling.sh"
retire_update_polling
configure_release_repository || die 'Invalid GitHub repository.'
if ! grep -q '^SPACEWORKS_REPOSITORY=' .env; then
  printf '\nSPACEWORKS_REPOSITORY=%s\n' "$SPACEWORKS_REPOSITORY" >> .env
fi
if [[ "$BUILD_FROM_SOURCE" == 0 ]]; then
  HOST_CONFIG_IMAGE="$MAKERSPACE_BACKEND_IMAGE:${MAKERSPACE_IMAGE_TAG:-latest}"
fi
if ! grep -q '^SPACEWORKS_EDITION=' .env; then
  printf '\nSPACEWORKS_EDITION=makerspace\n' >> .env
fi
# Existing installations predate the non-owner runtime database role. The privileged
# orchestration bootstrap creates/re-keys it before migrations or application startup.
if ! grep -q '^POSTGRES_APP_PASSWORD=' .env; then
  printf '\nPOSTGRES_APP_PASSWORD=%s\n' "$(rand_key 32)" >> .env
fi
if ! grep -q '^SPACEWORKS_SCHEDULER_MODE=' .env; then
  printf '\nSPACEWORKS_SCHEDULER_MODE=image\n' >> .env
fi
chmod 600 .env
mkdir -p "$ROOT/backups"
chmod 700 "$ROOT/backups"
prepare_compose_wrapper
source "$ROOT/scripts/compose-deployment.sh"
deployment_services
if [[ "$BUILD_FROM_SOURCE" == 1 ]]; then
  say "Building and starting the app from source (first run can take a few minutes)..."
  ${COMPOSE[@]+"${COMPOSE[@]}"} up -d --build
else
  say "Pulling release images (first run can take a few minutes)..."
  ${COMPOSE[@]+"${COMPOSE[@]}"} pull
  ${COMPOSE[@]+"${COMPOSE[@]}"} up -d
fi

# The deployment operation lock must be the same inode for backend, worker, beat and
# the privileged host scripts. Docker performs the ownership step so setup does not
# require host sudo merely to create uid 10001's bind mount.
if ! grep -q '^BACKUP_AGE_RECIPIENT=' .env; then
  ${COMPOSE[@]+"${COMPOSE[@]}"} exec -T "$APP_SERVICE" age-keygen \
    -o /var/lib/spaceworks/ops/work/age-identity.txt >/dev/null
  BACKUP_RECIPIENT="$(${COMPOSE[@]+"${COMPOSE[@]}"} exec -T "$APP_SERVICE" age-keygen \
    -y /var/lib/spaceworks/ops/work/age-identity.txt | tr -d '\r\n')"
  printf '\nBACKUP_AGE_RECIPIENT=%s\n' "$BACKUP_RECIPIENT" >> .env
  refresh_compose_config
  ${COMPOSE[@]+"${COMPOSE[@]}"} up -d
fi
if ! grep -q '^BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY=' .env; then
  SIGNING_PAIR="$(${COMPOSE[@]+"${COMPOSE[@]}"} exec -T "$APP_SERVICE" python -c 'from apps.ed25519 import encode_key,generate_keypair; p,q=generate_keypair(); print(encode_key(p)); print(encode_key(q))' | tr -d '\r')"
  printf '\nBACKUP_ARCHIVE_SIGNING_PRIVATE_KEY=%s\nBACKUP_ARCHIVE_VERIFY_PUBLIC_KEY=%s\n' "$(printf '%s\n' "$SIGNING_PAIR" | sed -n '1p')" "$(printf '%s\n' "$SIGNING_PAIR" | sed -n '2p')" >> .env
  refresh_compose_config
  ${COMPOSE[@]+"${COMPOSE[@]}"} up -d
fi
install_producer_capability

say "Waiting for the app to be ready..."
ready=0
for _ in $(seq 1 60); do
  if ${COMPOSE[@]+"${COMPOSE[@]}"} exec -T "$APP_SERVICE" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3)" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 3
done
[ "$ready" = 1 ] || die "The app did not become ready in time. Check logs with: ${COMPOSE[*]} logs backend"

if [ "$FIRST_RUN" = 1 ]; then
  say "Creating your admin account and makerspace..."
  SETUP_SUPERADMIN_PASSWORD="$ADMINPASS" SETUP_SUPERADMIN_USERNAME="$ADMINUSER" \
  SETUP_SUPERADMIN_EMAIL="$ADMINEMAIL" SETUP_MAKERSPACE_NAME="$MSNAME" SETUP_MAKERSPACE_SLUG="$MS_SUBDOMAIN" \
  ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T -e SETUP_SUPERADMIN_PASSWORD -e SETUP_SUPERADMIN_USERNAME \
    -e SETUP_SUPERADMIN_EMAIL -e SETUP_MAKERSPACE_NAME -e SETUP_MAKERSPACE_SLUG \
    backend --role management python manage.py setup_instance

  configure_setup_domain

  setup_areas_json | ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
    python manage.py apply_setup_areas --makerspace "$MS_SUBDOMAIN" --actor "$ADMINUSER" --answers-json - \
    || die 'Could not apply confirmed areas and settings. The private answers are retained for retry.'
  echo 'Areas and settings applied. Change them later with scripts/update.sh --modules-only or staff settings.'

  if [ -n "$GOOGLE_WEB_CLIENT_ID" ]; then
    say "Enabling Google sign-in..."
    if ! ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management python manage.py configure_social_auth \
      --google-web-client-id "$GOOGLE_WEB_CLIENT_ID"; then
      warn "Could not save the Google client ID. Add it later in Platform settings; password login is unaffected."
    fi
  fi

  if [ -n "$STRIPE_SECRET_KEY" ]; then
    configure_setup_stripe || die 'Could not safely save the online-payment credentials. Private answers are retained; resolve the settings error and retry setup.'
  fi

  if [[ "${INSTALL_RUNNER:-N}" =~ ^[Yy] ]]; then
    bash "$ROOT/scripts/install-runner.sh" \
      || die 'Runner installation failed. Retry with bash scripts/install-runner.sh.'
  fi

  say "All done!"
  rm -f -- "$ROOT/.spaceworks-answers"
  echo "  Website: $(deployment_value PUBLIC_APP_BASE_URL) (admin: $ADMINUSER)"
  echo "  API: $([[ "$HTTPS_MODE" == 1 ]] && echo http || echo https)://$WEBHOST/api"
  echo "  Control plane: /control/ on the backend only, through a private connection."
  [ "$GEN_PASS" = 1 ] && warn "  Generated admin password: ${ADMINPASS}   (save this now)"
  echo
  echo   "Next: log into the React staff console at /admin, add inventory, and turn on 'public inventory' for your makerspace."
else
  say "App started. To create the first admin (only if you haven't yet), run:"
  echo "  ${COMPOSE[*]} run --rm --no-deps backend --role management python manage.py setup_instance --username admin --password 'a-strong-password' --makerspace-name 'My Makerspace'"
fi

cleanup_run_once_jobs || warn "Could not remove finished start-up jobs."
