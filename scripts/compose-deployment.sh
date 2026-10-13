#!/usr/bin/env bash
# Read only non-secret topology selectors; never source dotenv as shell code.
deployment_value() {
  local value
  value="$(sed -n "s/^$1=//p" "${STATIC_ENV:-${SPACEWORKS_STATIC_ENV_FILE:-$ROOT/.env}}" 2>/dev/null | head -n 1)"
  value="${value#\'}"; value="${value%\'}"
  value="${value#\"}"; value="${value%\"}"
  printf '%s' "$value"
}

append_deployment_layers() {
  local layer="$1" prefix="$2"
  local frontend storage
  frontend="$(deployment_value SPACEWORKS_RUN_FRONTEND)"
  storage="$(deployment_value SPACEWORKS_STORAGE)"
  [[ -z "$frontend" || "$frontend" == yes || "$frontend" == no ]] || { echo 'SPACEWORKS_RUN_FRONTEND must be yes or no.' >&2; return 64; }
  [[ -z "$storage" || "$storage" == bundled || "$storage" == external ]] || { echo 'SPACEWORKS_STORAGE must be bundled or external.' >&2; return 64; }
  DEPLOYMENT_SUFFIX=''
  if [[ "$frontend" == no ]]; then
    COMPOSE_FILES+=("$prefix/docker/compose.api-only.yml")
    DEPLOYMENT_SUFFIX+='-api-only'
    if [[ "$layer" == *tls || "$layer" == *saas ]]; then
      COMPOSE_FILES+=("$prefix/docker/compose.api-only-edge.yml")
    fi
  fi
  if [[ "$storage" == external ]]; then
    COMPOSE_FILES+=("$prefix/docker/compose.external-storage.yml")
    DEPLOYMENT_SUFFIX+='-external-storage'
  fi
}
