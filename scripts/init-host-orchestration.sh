#!/usr/bin/env bash
# Provision the bundled H1 host state when published images are used.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || {
  echo "Copy .env.example to .env and fill every required secret first." >&2
  exit 64
}
grep -q '^POSTGRES_APP_PASSWORD=' .env || {
  echo ".env must declare the separate POSTGRES_APP_PASSWORD." >&2
  exit 64
}
grep -q '^SPACEWORKS_SCHEDULER_MODE=' .env || {
  echo ".env must declare SPACEWORKS_SCHEDULER_MODE." >&2
  exit 64
}
chmod 600 .env

image="${MAKERSPACE_BACKEND_IMAGE:-ghcr.io/spaceworks-hq/spaceworks-backend}"
tag="${MAKERSPACE_IMAGE_TAG:-latest}"
HOST_CONFIG_IMAGE="${image}:${tag}"
export SPACEWORKS_HOST_CONFIG_BUILD=0
source "$ROOT/scripts/setup-host-orchestration.sh"
prepare_compose_wrapper
install_producer_capability
