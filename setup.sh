#!/usr/bin/env bash
# Space Works - guided first-run setup (Linux, macOS, or Windows Git Bash/WSL).
# Run it from the project folder:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$PWD"
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
source "$ROOT/scripts/module-selection.sh"

# 1. Docker must be installed and running.
command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Desktop first: https://www.docker.com/products/docker-desktop/"
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop, then run this again."
docker compose version >/dev/null 2>&1 || die "The 'docker compose' plugin is missing. Update Docker Desktop."

# Subshell disables pipefail locally: `head` closing the pipe makes `tr` exit via SIGPIPE,
# which would otherwise abort the script under `set -o pipefail`.
rand_key()   { ( set +o pipefail; LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-50}" ); }
fernet_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }

choose_modules() {
  MODULE_MODE=interactive
  MODULE_INTERACTIVE=1
  MODULE_MAKERSPACE=""
  MODULE_ALL_MAKERSPACES=0
  MODULE_WITHOUT=""
  MODULE_CONFIRM_REMOVALS=0
  # The borrow-request answer IS the membership module, so the tick list opens with it
  # already set that way. The operator can still change it -- and if they do, the
  # read-back in apply_request_access wins, not the answer they gave earlier.
  MODULE_FORCE_ON=""
  MODULE_FORCE_OFF=""
  case "${REQUEST_ACCESS:-}" in
    members)          MODULE_FORCE_ON="membership" ;;
    accounts|anyone)  MODULE_FORCE_OFF="membership" ;;
  esac
  change_modules
}

# Deliberately AFTER choose_modules, and it re-reads the database rather than trusting
# $REQUEST_ACCESS. The operator may have ticked `membership` back on in the list above,
# and `membership` makes account-less requests impossible -- so the answer given three
# questions ago is a request, not the truth. Fail closed: if the flag cannot be opened,
# submission stays behind an account rather than being left open by accident.
apply_request_access() {
  local slug="$1" mode="${REQUEST_ACCESS:-accounts}"
  if [[ "$mode" == anyone ]]; then
    if ! "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py set_request_access --makerspace "$slug" --mode anyone; then
      warn "Account-less borrow requests were NOT enabled (the membership module is on)."
      warn "Borrow requests will require an account. Turn membership off and re-run:"
      warn "  ${COMPOSE[*]} run --rm --no-deps backend --role management python manage.py set_request_access --mode anyone"
      mode=members
    else
      return 0
    fi
  fi
  "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py set_request_access --makerspace "$slug" --mode "$mode" \
    || warn "Could not set who may submit borrow requests; the default (account required) stands."
}

FIRST_RUN=0
if [ -f .env ]; then
  say "Found an existing .env — keeping your settings and secrets."
else
  FIRST_RUN=1
  say "Welcome! Let's set up Space Works. Press Enter to accept the [default]."
  read -r -p "Web address (host name or IP, no http://) [localhost]: " WEBADDR;  WEBADDR="${WEBADDR:-localhost}"
  # Normalize: strip any scheme, path, and port so ALLOWED_HOSTS/CORS are valid.
  WEBHOST="${WEBADDR#*://}"; WEBHOST="${WEBHOST%%/*}"; WEBHOST="${WEBHOST%%:*}"
  [ -n "$WEBHOST" ] || WEBHOST="localhost"
  read -r -p "Name of your makerspace [My Makerspace]: "                   MSNAME;   MSNAME="${MSNAME:-My Makerspace}"
  # Modules are NOT asked here. The question moved to the end of setup, where the app is
  # running and the real registry can be read, so the operator ticks actual module names
  # instead of memorising profile words. `recommended` is only the starting point the tick
  # list opens with; nothing is final until that step.
  MSPROFILE="recommended"
  # Asked here with the other identity questions, applied at the very END of setup: the
  # answer implies the `membership` module, the module list is chosen after the app is
  # running, and the real state can only be read back from the database once both have
  # been applied. See apply_request_access.
  echo
  echo "Who can submit borrow requests?"
  echo "  1) Members only            - people you have enrolled as members of this makerspace"
  echo "  2) Anyone with an account  - any signed-in user; staff still accept every request"
  echo "  3) Anyone, no account      - a stranger leaves their name and contact details"
  echo "Option 3 is an unauthenticated write surface: it is rate limited, contact details are"
  echo "marked unverified, and no email is sent to them until you verify. You can change this"
  echo "later with 'manage.py set_request_access'."
  read -r -p "Choice [2]: " REQUEST_ACCESS_CHOICE
  case "${REQUEST_ACCESS_CHOICE:-2}" in
    1) REQUEST_ACCESS=members ;;
    3) REQUEST_ACCESS=anyone ;;
    2) REQUEST_ACCESS=accounts ;;
    *) warn "Unrecognised choice; requiring an account."; REQUEST_ACCESS=accounts ;;
  esac
  read -r -p "Admin login username [admin]: "                             ADMINUSER; ADMINUSER="${ADMINUSER:-admin}"
  read -r -p "Admin email [admin@example.com]: "                          ADMINEMAIL; ADMINEMAIL="${ADMINEMAIL:-admin@example.com}"
  read -r -s -p "Admin password (leave blank to auto-generate): "         ADMINPASS; echo
  GEN_PASS=0
  if [ -z "$ADMINPASS" ]; then ADMINPASS="$(rand_key 16)"; GEN_PASS=1; fi
  # Google sign-in is GUIDED, never automatic. Client IDs are issued by Google against
  # a specific origin, so no credential can ship in the box and "works out of the box"
  # is impossible here -- guided is the ceiling. Skipping leaves username/password
  # login fully working, which is the only login a fresh install has either way.
  echo
  echo "Optional: Google sign-in. To enable it you need a Google OAuth client ID:"
  echo "  1. Open https://console.cloud.google.com/apis/credentials"
  echo "  2. Create Credentials -> OAuth client ID -> Web application"
  echo "  3. Add this to 'Authorised JavaScript origins':  http://${WEBHOST}"
  echo "  4. Copy the Client ID (it ends in .apps.googleusercontent.com)"
  echo "Leave blank to skip — you can add it later in Platform settings."
  read -r -p "Google Web client ID (optional): " GOOGLE_WEB_CLIENT_ID
  GOOGLE_WEB_CLIENT_ID="$(printf '%s' "$GOOGLE_WEB_CLIENT_ID" | tr -d '[:space:]')"
  if [ -n "$GOOGLE_WEB_CLIENT_ID" ] && [[ "$GOOGLE_WEB_CLIENT_ID" != *.apps.googleusercontent.com ]]; then
    # Caught here rather than at first login: a wrong value makes the Google button
    # appear and then fail token verification for every user, with nothing on screen
    # explaining why.
    warn "That does not look like a Google client ID; skipping Google sign-in."
    GOOGLE_WEB_CLIENT_ID=""
  fi

  read -r -p "Stripe secret key (optional; leave blank to skip): " STRIPE_SECRET_KEY
  read -r -s -p "Stripe webhook secret (optional; leave blank to skip): " STRIPE_WEBHOOK_SECRET; echo
  read -r -p "Stripe default currency [usd]: " STRIPE_DEFAULT_CURRENCY; STRIPE_DEFAULT_CURRENCY="${STRIPE_DEFAULT_CURRENCY:-usd}"
  # Braces are load-bearing: && and || have EQUAL precedence in bash and associate left,
  # so the unbraced form parsed as ((A && B) || C) && D and silently accepted a secret key
  # with no webhook secret -- writing a half-configured Stripe account with no warning.
  if { [ -n "$STRIPE_SECRET_KEY" ] && [ -z "$STRIPE_WEBHOOK_SECRET" ]; } \
     || { [ -z "$STRIPE_SECRET_KEY" ] && [ -n "$STRIPE_WEBHOOK_SECRET" ]; }; then
    warn "Stripe needs both secrets; leaving payments unconfigured."
    STRIPE_SECRET_KEY=""; STRIPE_WEBHOOK_SECRET=""
  fi

  say "Writing .env (secrets generated automatically)..."
  cat > .env <<EOF
# Generated by setup.sh — keep this file private; it holds your secrets.
POSTGRES_PASSWORD=$(rand_key 32)
POSTGRES_APP_PASSWORD=$(rand_key 32)
MINIO_ROOT_USER=$(rand_key 24)
MINIO_ROOT_PASSWORD=$(rand_key 40)
SECRET_KEY=$(rand_key 50)
API_CLIENT_ENC_KEY=$(fernet_key)
AUDIT_MAC_MASTER_KEY=$(fernet_key)
ALLOWED_HOSTS=${WEBHOST},localhost,127.0.0.1,backend
CORS_ALLOWED_ORIGINS=http://${WEBHOST}
# Absolute base for links in outbound email (password reset, invitations). Without it
# those links are emitted as bare paths like "/reset-password?..." and are unclickable.
PUBLIC_APP_BASE_URL=http://${WEBHOST}
# Browser-facing object storage. These MUST name the address your users type, not
# localhost: they are baked into presigned evidence upload/view URLs and into every
# public image src. Left at the compose default (http://localhost:9000) the site works
# only from the server console and shows broken images to everyone else.
AWS_S3_PUBLIC_ENDPOINT_URL=http://${WEBHOST}:9000
PUBLIC_IMAGE_BASE_URL=http://${WEBHOST}:9000/public-images
# MinIO must accept browser uploads from the app's origin, or presigned POSTs are
# blocked by CORS before they ever reach storage.
MINIO_CORS_ALLOWED_ORIGINS=http://${WEBHOST}
HTTP_PORT=80
ENABLE_HTTPS=false
EOF
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
prepare_compose_wrapper
if [[ "$BUILD_FROM_SOURCE" == 1 ]]; then
  say "Building and starting the app from source (first run can take a few minutes)..."
  "${COMPOSE[@]}" up -d --build
else
  say "Pulling release images (first run can take a few minutes)..."
  "${COMPOSE[@]}" pull
  "${COMPOSE[@]}" up -d
fi

# The deployment operation lock must be the same inode for backend, worker, beat and
# the privileged host scripts. Docker performs the ownership step so setup does not
# require host sudo merely to create uid 10001's bind mount.
if ! grep -q '^BACKUP_AGE_RECIPIENT=' .env; then
  "${COMPOSE[@]}" exec -T backend age-keygen \
    -o /var/lib/spaceworks/ops/work/age-identity.txt >/dev/null
  BACKUP_RECIPIENT="$("${COMPOSE[@]}" exec -T backend age-keygen \
    -y /var/lib/spaceworks/ops/work/age-identity.txt | tr -d '\r\n')"
  printf '\nBACKUP_AGE_RECIPIENT=%s\n' "$BACKUP_RECIPIENT" >> .env
  refresh_compose_config
  "${COMPOSE[@]}" up -d
fi
if ! grep -q '^BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY=' .env; then
  SIGNING_PAIR="$("${COMPOSE[@]}" exec -T backend python -c 'from apps.ed25519 import encode_key,generate_keypair; p,q=generate_keypair(); print(encode_key(p)); print(encode_key(q))' | tr -d '\r')"
  printf '\nBACKUP_ARCHIVE_SIGNING_PRIVATE_KEY=%s\nBACKUP_ARCHIVE_VERIFY_PUBLIC_KEY=%s\n' "$(printf '%s\n' "$SIGNING_PAIR" | sed -n '1p')" "$(printf '%s\n' "$SIGNING_PAIR" | sed -n '2p')" >> .env
  refresh_compose_config
  "${COMPOSE[@]}" up -d
fi
install_producer_capability

say "Waiting for the app to be ready..."
ready=0
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/readiness/', timeout=3)" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 3
done
[ "$ready" = 1 ] || die "The app did not become ready in time. Check logs with: ${COMPOSE[*]} logs backend"

if [ "$FIRST_RUN" = 1 ]; then
  say "Creating your admin account and makerspace..."
  "${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py setup_instance \
    --username "$ADMINUSER" --email "$ADMINEMAIL" --password "$ADMINPASS" \
    --makerspace-name "$MSNAME" --profile "$MSPROFILE"

  if ! choose_modules; then
    warn "Module selection was not applied. Re-run scripts/update.sh --modules-only after fixing the message above."
  fi

  MS_SLUG="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py list_modules --json 2>/dev/null \
    | sed -n 's/.*"makerspace": *"\([^"]*\)".*/\1/p' | head -n 1)"
  if [ -n "$MS_SLUG" ]; then
    apply_request_access "$MS_SLUG"
  else
    warn "Could not read the makerspace back, so who may submit borrow requests was left at"
    warn "the default (an account is required). Set it with 'manage.py set_request_access'."
  fi

  if [ -n "$GOOGLE_WEB_CLIENT_ID" ]; then
    say "Enabling Google sign-in..."
    if ! "${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py configure_social_auth \
      --google-web-client-id "$GOOGLE_WEB_CLIENT_ID"; then
      warn "Could not save the Google client ID. Add it later in Platform settings; password login is unaffected."
    fi
  fi

  if [ -n "$STRIPE_SECRET_KEY" ]; then
    configure_setup_stripe
  fi

  read -r -p "Enable automatic production updates from main? [Y/n]: " AUTOUPDATE
  AUTOUPDATE="${AUTOUPDATE:-Y}"
  # ^[Yy] not ^[Yy]$: typing "yes" at a [Y/n] prompt previously fell through to the
  # off branch, which is the opposite of what the operator asked for.
  if [[ "$AUTOUPDATE" =~ ^[Yy] ]]; then
    if ! bash scripts/install-auto-update.sh; then
      warn "Could not install the seven-day updater. Run bash scripts/install-auto-update.sh later."
    fi
  else
    if bash scripts/install-auto-update.sh; then
      "${COMPOSE[@]}" run --rm --no-deps -T backend --role management python manage.py update_control set-auto off >/dev/null
      warn "Automatic installation is off. The host will still check for releases so Update now works from Platform settings."
    else
      warn "Could not install the seven-day update checker. Run bash scripts/install-auto-update.sh later, then turn automatic updates off in Platform settings."
    fi
  fi

  PORT="$(grep -E '^HTTP_PORT=' .env | cut -d= -f2)"; PORT="${PORT:-80}"
  HOST="$(grep -E '^ALLOWED_HOSTS=' .env | cut -d= -f2 | cut -d, -f1)"; HOST="${HOST:-localhost}"
  SUFFIX=""; [ "$PORT" != "80" ] && SUFFIX=":$PORT"
  say "All done! 🎉"
  echo   "  Public catalog : http://${HOST}${SUFFIX}/"
  echo   "  Staff console  : http://${HOST}${SUFFIX}/admin   (React, username: ${ADMINUSER})"
  echo   "  Control plane  : /control/ on the backend only; not published on the public port"
  [ "$GEN_PASS" = 1 ] && warn "  Generated admin password: ${ADMINPASS}   (save this now)"
  echo
  echo   "Next: log into the React staff console at /admin, add inventory, and turn on 'public inventory' for your makerspace."
else
  say "App started. To create the first admin (only if you haven't yet), run:"
  echo "  ${COMPOSE[*]} run --rm --no-deps backend --role management python manage.py setup_instance --username admin --password 'a-strong-password' --makerspace-name 'My Makerspace'"
fi
