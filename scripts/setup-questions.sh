#!/usr/bin/env bash
# No filesystem or Docker effects: gather every deployment choice, then confirm once.
source "$(dirname "${BASH_SOURCE[0]}")/setup-question-input.sh"

ask_setup_questions() {
  exec 3</dev/tty
  echo 'SpaceWorks deployment questions. Enter accepts the [default].'
  echo 'Hosting model:'
  echo '  1) One makerspace on this server - one community, at /m/<slug>.'
  echo '  2) Several makerspaces - shared server, each at /m/<slug>; the superadmin adds more later.'
  echo '  3) Hosted platform - each makerspace has a subdomain of your platform domain.'
  question HOSTING_MODEL 'Hosting model' 1 choices:1,2,3 || return 1
  PLATFORM_DOMAIN=''; PUBLIC_DOMAIN=''; TLS_EMAIL=''; SITE_ORIGINS=''
  if [[ "$HOSTING_MODEL" == 3 ]]; then
    question PLATFORM_DOMAIN 'Platform domain' '' domain || return 1
  fi
  echo 'Run the website (web frontend) on this server?'
  echo '  1) Yes - serve the website here.'
  echo '  2) No, API only - website hosted elsewhere (Netlify etc.).'
  question RUN_FRONTEND 'Website' 1 choices:1,2 || return 1
  if [[ "$RUN_FRONTEND" == 2 ]]; then
    question SITE_ORIGINS 'Site URL(s), comma-separated HTTPS origins (first is the staff site)' '' origins || return 1
  fi
  if [[ "$HOSTING_MODEL" == 3 ]]; then
    echo 'Hosted platforms require automatic HTTPS through the SaaS Caddy edge.'
    HTTPS_MODE=2
    question TLS_EMAIL 'HTTPS certificate email' '' email || return 1
  else
    echo 'HTTPS:'
    echo '  1) None - plain HTTP for a LAN or trial.'
    echo '  2) Automatic HTTPS - built-in Caddy; point DNS at this server.'
    echo '  3) I already run a reverse proxy - forward HTTPS to this server.'
    local https_default=1
    [[ "$RUN_FRONTEND" != 2 ]] || https_default=2
    while true; do
      question HTTPS_MODE 'HTTPS' "$https_default" choices:1,2,3 || return 1
      [[ "$RUN_FRONTEND" != 2 || "$HTTPS_MODE" != 1 ]] && break
      echo 'API-only with an external website requires HTTPS. Choose automatic HTTPS or an existing proxy.'
    done
    if [[ "$HTTPS_MODE" != 1 ]]; then
      question PUBLIC_DOMAIN 'Public API/server domain' '' domain || return 1
      [[ "$HTTPS_MODE" != 2 ]] || question TLS_EMAIL 'HTTPS certificate email' '' email || return 1
    fi
  fi
  echo 'How should it run?'
  echo '  1) Standard containers - separate API, worker, scheduler and web server.'
  echo '  2) Single box - one application container beside database and storage.'
  while true; do
    question SHAPE 'How it runs' 1 choices:1,2 || return 1
    if [[ "$SHAPE" == 2 && "${BUILD_FROM_SOURCE:-0}" == 1 ]]; then
      echo 'Single box requires the published all-in-one image. Choose standard containers for a source build.'
      continue
    fi
    [[ "$SHAPE" != 2 || ( "$RUN_FRONTEND" == 1 && "$HOSTING_MODEL" != 3 && "$HTTPS_MODE" == 1 ) ]] && break
    echo 'Single box cannot combine with API-only, hosted platform or HTTPS. Choose standard containers for these options.'
  done
  echo 'File storage:'
  echo '  1) Bundled Silo object storage - private evidence and public images on this server.'
  echo '  2) External S3-compatible buckets - provision buckets, versioning, privacy and CORS yourself.'
  question STORAGE 'File storage' 1 choices:1,2 || return 1
  S3_ENDPOINT=''; S3_REGION=us-east-1; PRIVATE_BUCKET=evidence; IMAGE_BUCKET=public-images
  S3_ACCESS_KEY=''; S3_SECRET_KEY=''; IMAGE_BASE_URL=''; PRESIGN_METHOD=post
  if [[ "$STORAGE" == 2 ]]; then
    local storage_url_rule=url
    [[ "$HTTPS_MODE" == 1 ]] || storage_url_rule=secure_url
    question S3_ENDPOINT 'S3 endpoint (also browser reachable)' '' "$storage_url_rule" || return 1
    question S3_REGION 'S3 region' us-east-1 region || return 1
    question PRIVATE_BUCKET 'Private evidence bucket' evidence bucket || return 1
    while true; do
      question IMAGE_BUCKET 'Public-image bucket' public-images bucket || return 1
      [[ "$IMAGE_BUCKET" != "$PRIVATE_BUCKET" ]] && break
      echo 'Private evidence and public images must use different buckets.'
    done
    question S3_ACCESS_KEY 'S3 access key' '' text || return 1
    while true; do
      question S3_SECRET_KEY 'S3 secret key' '' secret || return 1
      [[ -n "$S3_SECRET_KEY" ]] && break
      echo 'A secret key is required.'
    done
    question IMAGE_BASE_URL 'Public image base URL (includes bucket/path)' '' "$storage_url_rule" || return 1
    question PRESIGN_METHOD 'Presign method' post choices:put,post || return 1
  fi
  WEBHOST="$PUBLIC_DOMAIN"
  if [[ "$HOSTING_MODEL" == 3 ]]; then WEBHOST="$PLATFORM_DOMAIN"; fi
  [[ -n "$WEBHOST" ]] || question WEBHOST 'Web address (host name or IP, no http://)' localhost host || return 1
  question MSNAME 'Name of your makerspace' 'My Makerspace' name || return 1
  [[ "$HOSTING_MODEL" != 3 ]] || question MS_SUBDOMAIN 'First makerspace subdomain' makerspace slug || return 1
  echo 'What is this installation for?'
  echo '  1) A makerspace / tool library - lending, machines, events, bookings.'
  echo '  2) Events only - sign-ups and check-in.'
  echo '  3) Bookings only - rooms and resources.'
  echo '  4) An organization - makerspace features, labelled as an organization.'
  local edition
  question edition 'Edition' 1 choices:1,2,3,4 || return 1
  case "$edition" in
    1) SPACEWORKS_EDITION=makerspace ;; 2) SPACEWORKS_EDITION=events ;;
    3) SPACEWORKS_EDITION=bookings ;; 4) SPACEWORKS_EDITION=organization ;;
  esac
  echo 'Initial modules: recommended (inventory and machines), minimal (core only),'
  echo '  lending (tool library), workshop (machine shop), everything, events, or bookings.'
  local profile_default=recommended
  [[ "$SPACEWORKS_EDITION" != events && "$SPACEWORKS_EDITION" != bookings ]] || profile_default="$SPACEWORKS_EDITION"
  question MSPROFILE 'Initial modules' "$profile_default" choices:recommended,minimal,lending,workshop,everything,events,bookings || return 1
  echo 'Who can submit borrow requests?'
  echo '  1) Members only - people enrolled in this makerspace.'
  echo '  2) Anyone with an account - signed-in users; staff review requests.'
  echo '  3) Anyone, no account - rate-limited, unverified contact details; no email until verified.'
  local access
  question access 'Borrow requests' 2 choices:1,2,3 || return 1
  case "$access" in 1) REQUEST_ACCESS=members ;; 2) REQUEST_ACCESS=accounts ;; 3) REQUEST_ACCESS=anyone ;; esac
  question ADMINUSER 'Admin login username' admin username || return 1
  question ADMINEMAIL 'Admin email' '' email || return 1
  question ADMINPASS 'Admin password (blank generates one)' '' secret || return 1
  GEN_PASS=0
  if [[ -z "$ADMINPASS" ]]; then ADMINPASS="$(rand_key 24)"; GEN_PASS=1; fi
  echo "Optional Google sign-in: create a Web OAuth client at https://console.cloud.google.com/apis/credentials."
  local google_origin="$([[ "$HTTPS_MODE" == 1 ]] && echo http || echo https)://$WEBHOST"
  [[ "$HOSTING_MODEL" != 3 ]] || google_origin="https://$MS_SUBDOMAIN.$PLATFORM_DOMAIN"
  echo "Authorised JavaScript origin: ${SITE_ORIGINS:-$google_origin}"
  question GOOGLE_WEB_CLIENT_ID 'Google Web client ID' '' google || return 1
  while true; do
    question STRIPE_SECRET_KEY 'Stripe secret key' '' secret || return 1
    question STRIPE_WEBHOOK_SECRET 'Stripe webhook secret' '' secret || return 1
    [[ -z "$STRIPE_SECRET_KEY" && -z "$STRIPE_WEBHOOK_SECRET" || -n "$STRIPE_SECRET_KEY" && -n "$STRIPE_WEBHOOK_SECRET" ]] && break
    echo 'Stripe requires both secrets. Enter both or skip both.'
  done
  question STRIPE_DEFAULT_CURRENCY 'Stripe default currency' usd currency || return 1
  if [[ "${SPACEWORKS_INSTALL_REPOSITORY_PINNED:-0}" == 1 ]]; then
    echo "GitHub repository to follow [$SPACEWORKS_REPOSITORY] (selected before download)."
  else
    question SPACEWORKS_REPOSITORY 'GitHub repository to follow' "${SPACEWORKS_REPOSITORY:-SpaceWorks-HQ/SpaceWorks}" repository || return 1
  fi
  question DEPLOY_WEBHOOK 'Set up automatic deploys from GitHub releases?' Y choices:Y,y,yes,YES,N,n,no,NO || return 1
  setup_summary
  local proceed
  question proceed 'Proceed?' Y choices:Y,y,yes,YES,N,n,no,NO || return 1
  exec 3<&-
  [[ "$proceed" =~ ^[Yy] ]] || { echo 'Cancelled; nothing was installed or configured.'; return 1; }
  ANSWERS_CONFIRMED=yes
}

setup_summary() {
  echo
  echo 'Deployment summary'
  local hosting website https shape storage
  case "$HOSTING_MODEL" in 1) hosting='one makerspace' ;; 2) hosting='several makerspaces at /m/<slug>' ;; 3) hosting='hosted platform with tenant subdomains' ;; esac
  [[ "$RUN_FRONTEND" == 1 ]] && website=yes || website='API only, website elsewhere'
  case "$HTTPS_MODE" in 1) https='plain HTTP' ;; 2) https='automatic Caddy HTTPS' ;; 3) https='existing reverse proxy' ;; esac
  [[ "$SHAPE" == 1 ]] && shape='standard containers' || shape='single box'
  [[ "$STORAGE" == 1 ]] && storage='bundled Silo' || storage='external S3'
  printf '  Hosting model: %s; website: %s; HTTPS: %s; shape: %s; storage: %s\n' \
    "$hosting" "$website" "$https" "$shape" "$storage"
  printf '  Server: %s; platform: %s; certificate email: %s; external sites: %s\n' \
    "$WEBHOST" "${PLATFORM_DOMAIN:-none}" "${TLS_EMAIL:-none}" "${SITE_ORIGINS:-none}"
  printf '  Makerspace: %s; URL slug/subdomain: %s; edition: %s; request access: %s\n' \
    "$MSNAME" "${MS_SUBDOMAIN:-none}" "$SPACEWORKS_EDITION" "$REQUEST_ACCESS"
  echo "  Initial modules: $MSPROFILE; membership will be $([[ "$REQUEST_ACCESS" == members ]] && echo enabled || echo disabled) to match request access."
  printf '  Admin: %s <%s>; password: %s (hidden)\n' "$ADMINUSER" "$ADMINEMAIL" "$([[ "$GEN_PASS" == 1 ]] && echo generated || echo entered)"
  printf '  Google: %s; Stripe: %s; currency: %s; automatic release deploys: %s\n' \
    "${GOOGLE_WEB_CLIENT_ID:-skipped}" "$([[ -n "$STRIPE_SECRET_KEY" ]] && echo 'configured (secrets hidden)' || echo skipped)" "$STRIPE_DEFAULT_CURRENCY" "$DEPLOY_WEBHOOK"
  if [[ "$STORAGE" == 2 ]]; then
    printf '  S3: %s; region: %s; private bucket: %s; public bucket: %s\n' "$S3_ENDPOINT" "$S3_REGION" "$PRIVATE_BUCKET" "$IMAGE_BUCKET"
    printf '  Images: %s; presign: %s; access/secret keys: entered (hidden)\n' "$IMAGE_BASE_URL" "$PRESIGN_METHOD"
  fi
  echo "  GitHub repository: $SPACEWORKS_REPOSITORY"
  if [[ "$DEPLOY_WEBHOOK" =~ ^[Yy] ]]; then
    echo "  Deploy webhook: https://$WEBHOST/hooks/deploy (GitHub requires public HTTPS)."
  fi
  echo "  migrate builds the database tables. It runs once and stops. It's required."
  echo "  orchestration is a start-up safety check. It runs once and stops. It's required."
  local services='database, Redis'
  [[ "$STORAGE" != 1 ]] || services+=', Silo storage (bucket initializer)'
  if [[ "$SHAPE" == 2 ]]; then
    services+=', single application (API, live events, worker, scheduler, website)'
  else
    services+=', API, live events, worker, scheduler'
    [[ "$RUN_FRONTEND" == 2 ]] && services+=', API edge' || services+=', website'
    [[ "$HTTPS_MODE" != 2 ]] || services+=', Caddy HTTPS edge'
  fi
  [[ ! "$DEPLOY_WEBHOOK" =~ ^[Yy] ]] || services+=', deploy webhook receiver and host trigger'
  echo "  Will run: $services; one-shot database/orchestration initialization and migrations."
  if [[ "$HOSTING_MODEL" == 3 ]]; then
    echo "  API origin: https://$MS_SUBDOMAIN.$PLATFORM_DOMAIN (also https://$PLATFORM_DOMAIN)."
    echo "  DNS: point the platform apex, origin and tenant subdomains at this server."
  elif [[ "$HTTPS_MODE" != 1 ]]; then
    echo "  API origin: https://$WEBHOST. Point its DNS at this server/proxy."
  fi
  if [[ "$STORAGE" == 1 && "$HTTPS_MODE" != 1 ]]; then
    echo "  Storage DNS: files.${PLATFORM_DOMAIN:-$WEBHOST} must point at this server/proxy."
    [[ "$HTTPS_MODE" != 3 ]] || echo "  Existing proxy must forward files.$WEBHOST to 127.0.0.1:9000 and the API/site to 127.0.0.1:8080, preserving Host and X-Forwarded-Proto: https."
  fi
  echo "  Will perform: ${SETUP_HOST_PLAN:-write private .env and topology, pull/build images, create your admin and makerspace, apply selected modules, start services and install the selected release webhook trigger}."
  echo '  Production contains no demo or example data. Secrets are saved privately, never printed here.'
}
