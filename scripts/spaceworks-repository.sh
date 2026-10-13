#!/usr/bin/env bash
# Read only named configuration values; never execute the private .env as shell code.
repository_env_value() {
  local key="$1" value="" file="${SPACEWORKS_STATIC_ENV_FILE:-$ROOT/.env}"
  if [[ -f "$file" ]]; then
    value="$(sed -n "s/^${key}=//p" "$file" | tail -n 1 | tr -d '\r')"
    if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
  fi
  printf '%s' "$value"
}

configure_release_repository() {
  local owner key value
  SPACEWORKS_REPOSITORY="${SPACEWORKS_REPOSITORY:-$(repository_env_value SPACEWORKS_REPOSITORY)}"
  SPACEWORKS_REPOSITORY="${SPACEWORKS_REPOSITORY:-SpaceWorks-HQ/SpaceWorks}"
  [[ "$SPACEWORKS_REPOSITORY" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9_.-]{1,100}$ ]] \
    && [[ "$SPACEWORKS_REPOSITORY" != */. && "$SPACEWORKS_REPOSITORY" != */.. ]] || {
    printf 'ERROR: SPACEWORKS_REPOSITORY must be a GitHub owner/repo name.\n' >&2
    return 1
  }
  owner="$(printf '%s' "${SPACEWORKS_REPOSITORY%%/*}" | tr '[:upper:]' '[:lower:]')"
  for key in MAKERSPACE_BACKEND_IMAGE MAKERSPACE_FRONTEND_IMAGE MAKERSPACE_ALLINONE_IMAGE; do
    value="${!key:-$(repository_env_value "$key")}"
    if [[ -z "$value" ]]; then
      case "$key" in
        MAKERSPACE_BACKEND_IMAGE) value="ghcr.io/$owner/spaceworks-backend" ;;
        MAKERSPACE_FRONTEND_IMAGE) value="ghcr.io/$owner/spaceworks-frontend" ;;
        MAKERSPACE_ALLINONE_IMAGE) value="ghcr.io/$owner/spaceworks-allinone" ;;
      esac
    fi
    export "$key=$value"
  done
  export SPACEWORKS_REPOSITORY
}
