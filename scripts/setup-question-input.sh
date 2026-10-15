#!/usr/bin/env bash
# Input and private answer transport shared by the fetched and checkout installers.
rand_key() { ( set +o pipefail; LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-50}" ); }
fernet_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_'; }

valid_dns_host() {
  local host="$1" label
  [[ ${#host} -le 253 && "$host" != *..* && "$host" != *. ]] || return 1
  IFS=. read -ra host_labels <<< "$host"
  for label in "${host_labels[@]}"; do
    [[ ${#label} -le 63 && "$label" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$ ]] || return 1
  done
  [[ ${#host_labels[@]} -gt 0 ]]
}

valid_storage_url() {
  local authority host port
  [[ "$1" != *@* && "$1" != *\?* && "$1" != *\#* ]] || return 1
  authority="${1#*://}"; authority="${authority%%/*}"
  host="${authority%%:*}"
  valid_dns_host "$host" || return 1
  if [[ "$authority" == *:* ]]; then
    port="${authority##*:}"
    [[ "$port" =~ ^[0-9]{1,5}$ ]] && ((10#$port > 0 && 10#$port <= 65535)) || return 1
  fi
}

question() {
  local key="$1" label="$2" default="$3" rule="${4:-text}" value
  while true; do
    local hint="${default:-required}"
    case "$rule" in secret|google) hint="${default:-skip}" ;; esac
    [[ "$key" != ADMINPASS ]] || hint=auto-generate
    [[ "$key" != S3_SECRET_KEY ]] || hint=required
    if [[ "$rule" == choices:Y,* ]]; then
      [[ "$default" =~ ^[Yy] ]] && hint=Y/n || hint=y/N
    fi
    printf '%s [%s]: ' "$label" "$hint"
    if [[ "$rule" == secret ]]; then
      IFS= read -r -s -u 3 value || return 1
      echo
    else
      IFS= read -r -u 3 value || return 1
    fi
    value="${value%$'\r'}"
    value="${value:-$default}"
    case "$rule" in
      choices:*) [[ ",${rule#choices:}," == *",$value,"* ]] || { echo 'Choose one of the listed options.'; continue; } ;;
      integer:*)
        local bounds="${rule#integer:}" minimum maximum
        minimum="${bounds%%:*}"; maximum="${bounds##*:}"
        [[ "$value" =~ ^[0-9]{1,10}$ ]] && ((10#$value >= minimum && 10#$value <= maximum)) || { echo "Use a whole number from $minimum to $maximum."; continue; }
        ;;
      money) [[ "$value" =~ ^[0-9]{1,10}([.][0-9]{1,2})?$ ]] || { echo 'Use a non-negative amount with at most two decimals.'; continue; } ;;
      clock) [[ "$value" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || { echo 'Use local HH:MM (00:00 to 23:59).'; continue; } ;;
      timezone)
        [[ "$value" =~ ^[A-Za-z][A-Za-z0-9_+/-]*$ && "$value" != *..* ]] || { echo 'Use an IANA timezone such as UTC or Asia/Kolkata.'; continue; }
        if [[ -d /usr/share/zoneinfo && "$value" != UTC && ! -f "/usr/share/zoneinfo/$value" ]]; then
          echo 'That IANA timezone is not installed on this host.'; continue
        fi ;;
      days) [[ "$value" == none || "$value" =~ ^[1-9][0-9]{0,2}(,[1-9][0-9]{0,2}){0,9}$ ]] || { echo 'Use up to ten comma-separated days, or none.'; continue; }
        if [[ "$value" != none ]]; then
          local day invalid=0; local days=(); IFS=, read -ra days <<< "$value"
          for day in "${days[@]}"; do ((day <= 365)) || invalid=1; done
          [[ "$invalid" == 0 ]] || { echo 'Days must be from 1 to 365.'; continue; }
        fi ;;
      repository) [[ "$value" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}$ && "$value" != */. && "$value" != */.. ]] || { echo 'Enter a GitHub owner/repo name.'; continue; } ;;
      host) valid_dns_host "$value" || { echo 'Enter a hostname or IPv4 address without a scheme, port or path.'; continue; } ;;
      domain) [[ "$value" == *.* && ! "${value##*.}" =~ ^[0-9]+$ ]] && valid_dns_host "$value" || { echo 'Enter a DNS domain without a scheme, port or path.'; continue; }; value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" ;;
      slug)
        [[ "$value" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ && ${#value} -le 50 ]] || { echo 'Use up to 50 lowercase letters, digits and hyphens.'; continue; }
        case "$value" in www|api|app|admin|control|static|files|origin|mail|cdn|assets|status|help|docs|blog|portal|dashboard) echo 'That subdomain is reserved.'; continue ;; esac
        ;;
      email) [[ "$value" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] || { echo 'Enter an email address.'; continue; } ;;
      name)
        local derived_slug
        derived_slug="$(printf '%s' "$value" | LC_ALL=C tr '[:upper:]' '[:lower:]' | LC_ALL=C sed 's/[^a-z0-9 _-]//g; s/[ _-][ _-]*/-/g; s/^-//; s/-$//')"
        [[ ${#value} -le 200 && -n "$derived_slug" && ${#derived_slug} -le 50 ]] || { echo 'Use a name with a URL slug of 1-50 letters/digits/hyphens (include ASCII letters or digits).'; continue; }
        MS_SUBDOMAIN="$derived_slug"
        ;;
      origins)
        local origin valid=1
        IFS=, read -ra origin_list <<< "$value"
        for origin in "${origin_list[@]}"; do
          [[ "$origin" =~ ^https://[a-zA-Z0-9.-]+$ ]] || valid=0
          valid_dns_host "${origin#https://}" || valid=0
        done
        [[ "$valid" == 1 && "$value" != *, ]] || { echo 'Enter comma-separated HTTPS origins, without paths or trailing slashes.'; continue; }
        value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
        ;;
      bucket) [[ "$value" =~ ^[a-z0-9][a-z0-9.-]+[a-z0-9]$ && ${#value} -le 63 && "$value" != *..* ]] || { echo 'Use a bucket name of 3-63 lowercase letters, digits, dots or hyphens.'; continue; } ;;
      url) [[ "$value" =~ ^https?://[^[:space:]\'\"\$\`]+$ ]] || { echo 'Enter an http:// or https:// URL.'; continue; } ;;
      secure_url) [[ "$value" =~ ^https://[^[:space:]\'\"\$\`]+$ ]] || { echo 'HTTPS websites require an https:// storage URL.'; continue; } ;;
      google) [[ -z "$value" || "$value" == *.apps.googleusercontent.com ]] || { echo 'A Google client ID ends in .apps.googleusercontent.com.'; continue; } ;;
      currency) [[ "$value" =~ ^[a-z]{3}$ ]] || { echo 'Use a three-letter lowercase currency code.'; continue; } ;;
      region) [[ "$value" =~ ^[a-zA-Z0-9._-]+$ ]] || { echo 'Enter a region code without whitespace.'; continue; } ;;
      username) [[ "$value" =~ ^[a-zA-Z0-9_.@+-]+$ ]] || { echo 'Use letters, digits or . @ + - _.'; continue; } ;;
      text) [[ -n "$value" ]] || { echo 'A value is required.'; continue; } ;;
    esac
    if [[ "$rule" == url || "$rule" == secure_url ]]; then
      valid_storage_url "$value" || { echo 'Enter a valid storage URL without embedded credentials, query or fragment.'; continue; }
    fi
    [[ "$value" != *$'\r'* && "$value" != *$'\n'* ]] || { echo 'Use a single line.'; continue; }
    [[ "$rule" == secret || ! "$value" =~ [[:cntrl:]] ]] || { echo 'Use text without control characters.'; continue; }
    [[ "$key" != ADMINUSER || ${#value} -le 150 ]] || { echo 'Usernames are limited to 150 characters.'; continue; }
    [[ "$key" != ADMINEMAIL || ${#value} -le 254 ]] || { echo 'Email addresses are limited to 254 characters.'; continue; }
    printf -v "$key" '%s' "$value"
    return 0
  done
}

SETUP_ANSWER_KEYS=(HOSTING_MODEL RUN_FRONTEND SITE_ORIGINS PLATFORM_DOMAIN PUBLIC_DOMAIN
  TLS_EMAIL HTTPS_MODE SHAPE STORAGE WEBHOST MSNAME MS_SUBDOMAIN SPACEWORKS_EDITION
  SETUP_SELECTED_AREAS AREA_SETTINGS_JSON AREA_ORGANIZATION AREA_CREATE_PLAN REQUEST_ACCESS ADMINUSER ADMINEMAIL ADMINPASS GEN_PASS GOOGLE_WEB_CLIENT_ID
  STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_DEFAULT_CURRENCY SPACEWORKS_REPOSITORY INSTALL_RUNNER
  S3_ENDPOINT S3_REGION PRIVATE_BUCKET IMAGE_BUCKET S3_ACCESS_KEY S3_SECRET_KEY
  IMAGE_BASE_URL PRESIGN_METHOD ANSWERS_CONFIRMED)

save_setup_answers() {
  local target="$1" key
  (umask 077; set -o noclobber; : > "$target") || return 1
  chmod 600 "$target"
  for key in "${SETUP_ANSWER_KEYS[@]}"; do
    printf '%s=%q\n' "$key" "${!key:-}" >> "$target"
  done
}

persist_setup_answers() {
  local key
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      # Native Windows cannot represent POSIX mode 600 reliably. Inherit the
      # confirmed answers in process environment instead of writing a secret file.
      for key in "${SETUP_ANSWER_KEYS[@]}"; do export "$key"; done
      ;;
    *) save_setup_answers "$1" ;;
  esac
}

load_setup_answers() {
  local target="$1" mode
  [[ -f "$target" && ! -L "$target" && -O "$target" ]] || { echo 'Answers must be a regular file owned by the operator.' >&2; return 1; }
  mode="$(stat -c %a "$target" 2>/dev/null || stat -f %Lp "$target")"
  [[ "$mode" == 600 ]] || { echo 'Answers file must have mode 600.' >&2; return 1; }
  source "$target"
  [[ "${ANSWERS_CONFIRMED:-}" == yes ]] || { echo 'Deployment answers have not been confirmed.' >&2; return 1; }
}
