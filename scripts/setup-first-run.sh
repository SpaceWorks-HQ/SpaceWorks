#!/usr/bin/env bash
# Sourced by setup.sh; guided initial settings and private .env creation.
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
  # Edition: what this box is FOR. The loan spine is core and always present; an edition
  # only decides which surfaces are shown and which public routes answer (docs/MODULES.md,
  # "Editions"). Stored in .env as SPACEWORKS_EDITION and changeable later.
  echo
  echo "What is this installation for?"
  echo "  1) A makerspace / tool library  - lending, machines, events, bookings (default)"
  echo "  2) Events only                  - an events programme with sign-ups and check-in"
  echo "  3) Bookings only                - rooms and resources people reserve"
  echo "  4) An organization              - the same as 1, labelled as an organization"
  read -r -p "Choice [1]: " EDITION_CHOICE
  case "${EDITION_CHOICE:-1}" in
    2) SPACEWORKS_EDITION="events" ;;
    3) SPACEWORKS_EDITION="bookings" ;;
    4) SPACEWORKS_EDITION="organization" ;;
    *) SPACEWORKS_EDITION="makerspace" ;;
  esac
  # Install shape: several containers (default) or one application container beside the
  # database and object storage. Same image contents, same rules; fewer things to run.
  echo
  echo "How should it run?"
  echo "  1) Standard    - separate containers for the API, worker, scheduler and web server"
  echo "  2) Single box  - one application container (plus the database and storage)"
  read -r -p "Choice [1]: " SHAPE_CHOICE
  if [ "${SHAPE_CHOICE:-1}" = 2 ]; then
    printf 'single\n' > "$ROOT/.spaceworks-layer"
    export SPACEWORKS_COMPOSE_LAYER=single
  else
    rm -f "$ROOT/.spaceworks-layer"
  fi
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
SPACEWORKS_EDITION=${SPACEWORKS_EDITION:-makerspace}
EOF
fi
