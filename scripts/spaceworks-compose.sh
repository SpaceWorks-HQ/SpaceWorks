#!/usr/bin/env bash
# Load-bearing Compose launcher: static config first, atomic DB pointer last.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOPOLOGY="${1:-}"
[[ "$TOPOLOGY" == "bundled" || "$TOPOLOGY" == "cloud" ]] || {
  echo "usage: scripts/spaceworks-compose.sh <bundled|cloud> [compose arguments...]" >&2
  exit 64
}
shift

for argument in "$@"; do
  case "$argument" in
    -f|--file|--file=*|-f*|--env-file|--env-file=*|--project-directory|--project-directory=*)
      echo "Compose file, env-file and project-directory overrides are forbidden by the committed wrapper." >&2
      exit 64
      ;;
  esac
done

OPS_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
POINTER="$OPS_DIR/database-pointer.env"
RECORD="$OPS_DIR/compose-topology.json"
if [[ "$TOPOLOGY" == "bundled" ]]; then
  STATIC_ENV="${SPACEWORKS_STATIC_ENV_FILE:-$ROOT/.env}"
  COMPOSE_FILES=("$ROOT/docker-compose.prod.yml")
else
  STATIC_ENV="${SPACEWORKS_STATIC_ENV_FILE:-/etc/spaceworks/cloud.env}"
  COMPOSE_FILES=("$ROOT/docker-compose.cloud.yml")
fi
LAYER="${SPACEWORKS_COMPOSE_LAYER:-}"
if [[ -z "$LAYER" && "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" == "1" ]]; then
  LAYER="build"
fi
LAYER="${LAYER:-none}"
if [[ "$TOPOLOGY" == "cloud" && "$LAYER" != "none" ]]; then
  echo "Named Compose overlays are available only for bundled topology." >&2
  exit 64
fi
case "$LAYER" in
  none) ;;
  build) COMPOSE_FILES+=("$ROOT/docker/compose.build.yml") ;;
  tls) COMPOSE_FILES+=("$ROOT/docker/compose.tls.yml") ;;
  build-tls)
    COMPOSE_FILES+=("$ROOT/docker/compose.build.yml" "$ROOT/docker/compose.tls.yml")
    ;;
  saas) COMPOSE_FILES+=("$ROOT/docker/compose.saas.yml") ;;
  build-saas)
    COMPOSE_FILES+=("$ROOT/docker/compose.build.yml" "$ROOT/docker/compose.saas.yml")
    ;;
  *)
    echo "Unknown Compose layer; use none, build, tls, build-tls, saas, or build-saas." >&2
    exit 64
    ;;
esac
if [[ "$LAYER" != "none" ]]; then
  RECORD="$OPS_DIR/compose-topology-$LAYER.json"
fi

VALIDATE=(python3 "$ROOT/scripts/validate-compose-wrapper.py"
  --topology "$TOPOLOGY" --static-env "$STATIC_ENV"
  --pointer "$POINTER" --record "$RECORD")
COMPOSE_ARGS=(--env-file "$STATIC_ENV" --env-file "$POINTER")
for file in "${COMPOSE_FILES[@]}"; do
  VALIDATE+=(--compose-file "$file")
  COMPOSE_ARGS+=(-f "$file")
done
"${VALIDATE[@]}"

# Shell values outrank every --env-file during interpolation. Remove both pointer
# names before Docker Compose starts so only the final pointer file can define them.
unset DATABASE_URL
unset SPACEWORKS_DB_POINTER_GENERATION
exec docker compose "${COMPOSE_ARGS[@]}" "$@"
