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

# Service sets follow the saved topology, including on updates and recovery.
deployment_services() {
  local layer="${SPACEWORKS_COMPOSE_LAYER:-}" frontend
  if [[ -z "$layer" && -f "$ROOT/.spaceworks-layer" ]]; then
    layer="$(tr -d '[:space:]' < "$ROOT/.spaceworks-layer")"
  fi
  APP_SERVICE=backend
  WORKER_SERVICES=(worker beat live)
  IMAGE_SERVICES=(orchestration-init migrate orchestration-ready backend live worker beat)
  ROLLBACK_SERVICES=(backend live worker beat)
  RUN_ONCE_SERVICES=(orchestration-init migrate orchestration-ready)
  if [[ "$layer" == single ]]; then
    APP_SERVICE=app
    WORKER_SERVICES=()
    IMAGE_SERVICES=(orchestration-init migrate orchestration-ready app)
    ROLLBACK_SERVICES=(app)
  elif [[ "$(deployment_value SPACEWORKS_RUN_FRONTEND)" == no ]]; then
    IMAGE_SERVICES+=(api-edge)
    ROLLBACK_SERVICES+=(api-edge)
  else
    IMAGE_SERVICES+=(frontend)
    ROLLBACK_SERVICES+=(frontend)
  fi
  # The isolated receiver stays present even when disabled: an empty secret refuses
  # deliveries, and static nginx upstreams must resolve before nginx can start.
  IMAGE_SERVICES+=(deploy-webhook)
  ROLLBACK_SERVICES+=(deploy-webhook)
  [[ "$(deployment_value SPACEWORKS_STORAGE)" == external ]] || RUN_ONCE_SERVICES+=(createbuckets)
}
