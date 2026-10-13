#!/usr/bin/env bash
# Load-bearing Compose launcher: static config first, atomic DB pointer last.
set -euo pipefail

WRAPPER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${SPACEWORKS_UPDATE_INSTALL_DIR:-$(cd "$WRAPPER_SCRIPT_DIR/.." && pwd)}"
export SPACEWORKS_UPDATE_INSTALL_DIR="$ROOT"
source "$WRAPPER_SCRIPT_DIR/spaceworks-repository.sh"
configure_release_repository
TOPOLOGY="${1:-}"
[[ "$TOPOLOGY" == "bundled" || "$TOPOLOGY" == "cloud" ]] || {
  echo "usage: scripts/spaceworks-compose.sh <bundled|cloud> [compose arguments...]" >&2
  exit 64
}
shift

# A curl install writes the exact release only after setup succeeds. Keep every
# later Compose invocation on that reproducible tag unless the operator/update
# process explicitly supplies a different one in the shell.
if [[ -z "${MAKERSPACE_IMAGE_TAG:-}" && -f "$ROOT/.spaceworks-version" ]] \
  && { [[ ! -f "$ROOT/.env" ]] || ! grep -q '^MAKERSPACE_IMAGE_TAG=.' "$ROOT/.env"; }; then
  pinned_tag="$(tr -d '[:space:]' < "$ROOT/.spaceworks-version")"
  [[ "$pinned_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
    echo "Invalid image tag in $ROOT/.spaceworks-version." >&2
    exit 64
  }
  export MAKERSPACE_IMAGE_TAG="$pinned_tag"
fi

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
# The install shape chosen at setup persists here so an update never silently changes a
# single-box install back into the multi-service one (or vice versa).
if [[ -z "$LAYER" && -f "$ROOT/.spaceworks-layer" ]]; then
  LAYER="$(tr -d '[:space:]' < "$ROOT/.spaceworks-layer")"
  [[ "$LAYER" =~ ^[a-z-]+$ ]] || { echo "Invalid layer in $ROOT/.spaceworks-layer." >&2; exit 64; }
fi
LAYER="${LAYER:-none}"
if [[ "${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" == 1 ]]; then
  case "$LAYER" in
    none) LAYER=build ;;
    tls|saas) LAYER="build-$LAYER" ;;
  esac
fi
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
  # The single-box shape: parks the multi-service processes behind an inactive profile and
  # activates the `app` service the base file declares under `profiles: ["single"]`.
  single)
    COMPOSE_FILES+=("$ROOT/docker/compose.single.yml")
    export COMPOSE_PROFILES="single${COMPOSE_PROFILES:+,$COMPOSE_PROFILES}"
    ;;
  *)
    echo "Unknown Compose layer; use none, build, tls, build-tls, saas, build-saas, or single." >&2
    exit 64
    ;;
esac
if [[ "$LAYER" != "none" ]]; then
  RECORD="$OPS_DIR/compose-topology-$LAYER.json"
fi
source "$WRAPPER_SCRIPT_DIR/compose-deployment.sh"
if [[ "$TOPOLOGY" == bundled ]]; then
  append_deployment_layers "$LAYER" "$ROOT"
  RECORD="${RECORD%.json}${DEPLOYMENT_SUFFIX}.json"
  if [[ "$LAYER" == *tls ]]; then
    export COMPOSE_PROFILES="tls${COMPOSE_PROFILES:+,$COMPOSE_PROFILES}"
  fi
fi

VALIDATE=(python3 "$WRAPPER_SCRIPT_DIR/validate-compose-wrapper.py"
  --topology "$TOPOLOGY" --static-env "$STATIC_ENV"
  --pointer "$POINTER" --record "$RECORD")
COMPOSE_ARGS=(--env-file "$STATIC_ENV" --env-file "$POINTER")
for file in ${COMPOSE_FILES[@]+"${COMPOSE_FILES[@]}"}; do
  VALIDATE+=(--compose-file "$file")
  COMPOSE_ARGS+=(-f "$file")
done
if command -v python3 >/dev/null 2>&1 \
  && python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
  ${VALIDATE[@]+"${VALIDATE[@]}"}
else
  # Minimal Linux hosts need no host Python. Validate as the host UID so the
  # same static-env owner check applies; retain supplementary read groups.
  image="${HOST_CONFIG_IMAGE:-${MAKERSPACE_BACKEND_IMAGE:-ghcr.io/spaceworks-hq/spaceworks-backend}:${MAKERSPACE_IMAGE_TAG:-latest}}"
  groups=()
  for gid in $(id -G); do groups+=(--group-add "$gid"); done
  container_args=(--topology "$TOPOLOGY" --static-env /static.env
    --pointer /ops/database-pointer.env --record "/ops/$(basename "$RECORD")")
  for file in ${COMPOSE_FILES[@]+"${COMPOSE_FILES[@]}"}; do
    container_args+=(--compose-file "/repo/${file#"$ROOT/"}")
  done
  MSYS_NO_PATHCONV=1 docker run --rm --network none --read-only \
    --user "$(id -u):$(id -g)" ${groups[@]+"${groups[@]}"} --entrypoint python \
    -e SPACEWORKS_UPDATE_INSTALL_DIR=/repo \
    -v "$ROOT:/repo:ro" -v "$STATIC_ENV:/static.env:ro" -v "$OPS_DIR:/ops:ro" \
    -v "$WRAPPER_SCRIPT_DIR/..:/validation-code:ro" \
    "$image" /validation-code/scripts/validate-compose-wrapper.py ${container_args[@]+"${container_args[@]}"}
fi

# Shell values outrank every --env-file during interpolation. Remove both pointer
# names before Docker Compose starts so only the final pointer file can define them.
unset DATABASE_URL
unset SPACEWORKS_DB_POINTER_GENERATION
exec docker compose ${COMPOSE_ARGS[@]+"${COMPOSE_ARGS[@]}"} "$@"
