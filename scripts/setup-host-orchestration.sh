#!/usr/bin/env bash
# Sourced by setup.sh; prepares root-owned host orchestration state.

record_compose_config() {
  local record="$1"; shift
  docker run --rm --user 0:0 --entrypoint python \
    -v "$ROOT:/repo:ro" -v "$OPS_HOST_DIR:/ops" "$HOST_CONFIG_IMAGE" \
    /repo/scripts/configure-compose-wrapper.py record-config \
    --topology bundled --static-env /repo/.env \
    --pointer /ops/database-pointer.env --record "/ops/$record" \
    --compose-file /repo/docker-compose.prod.yml --reader-gid "$(id -g)" "$@"
}

refresh_compose_config() {
  record_compose_config compose-topology.json
  record_compose_config compose-topology-build.json \
    --compose-file /repo/docker/compose.build.yml
  record_compose_config compose-topology-tls.json \
    --compose-file /repo/docker/compose.tls.yml
  record_compose_config compose-topology-build-tls.json \
    --compose-file /repo/docker/compose.build.yml \
    --compose-file /repo/docker/compose.tls.yml
  record_compose_config compose-topology-saas.json \
    --compose-file /repo/docker/compose.saas.yml
  record_compose_config compose-topology-build-saas.json \
    --compose-file /repo/docker/compose.build.yml \
    --compose-file /repo/docker/compose.saas.yml
}

prepare_compose_wrapper() {
  local host_gid
  host_gid="$(id -g)"
  OPS_HOST_DIR="${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}"
  export OPS_HOST_DIR
  if [[ "${SPACEWORKS_HOST_CONFIG_BUILD:-1}" == "1" ]]; then
    docker build -q -t "$HOST_CONFIG_IMAGE" "$ROOT/backend" >/dev/null
  else
    docker pull "$HOST_CONFIG_IMAGE" >/dev/null
  fi
  docker run --rm --user 0:0 --entrypoint sh \
    -v "$OPS_HOST_DIR:/ops" "$HOST_CONFIG_IMAGE" -c \
    "mkdir -p /ops/work && chown 10001:10001 /ops/work && chmod 700 /ops/work && touch /ops/operation.lock && chown 0:0 /ops/operation.lock && chmod 666 /ops/operation.lock && chown 0:$host_gid /ops && chmod 750 /ops"
  if ! docker run --rm --user 0:0 --entrypoint test \
    -v "$OPS_HOST_DIR:/ops" "$HOST_CONFIG_IMAGE" -f /ops/database-pointer.env; then
    python3 "$ROOT/scripts/bundled-database-url.py" "$ROOT/.env" | \
      docker run --rm -i --user 0:0 --entrypoint python \
      -v "$ROOT:/repo:ro" -v "$OPS_HOST_DIR:/ops" "$HOST_CONFIG_IMAGE" \
      /repo/scripts/configure-compose-wrapper.py initialize-pointer \
      --topology bundled --static-env /repo/.env \
      --pointer /ops/database-pointer.env --record /ops/compose-topology.json \
      --compose-file /repo/docker-compose.prod.yml --reader-gid "$(id -g)"
  fi
  refresh_compose_config
  HOST_STATE_DIR="${SPACEWORKS_HOST_STATE_DIR:-/var/lib/spaceworks/host}"
  docker run --rm --user 0:0 --entrypoint python \
    -v "$ROOT:/repo:ro" -v "$HOST_STATE_DIR:/state" "$HOST_CONFIG_IMAGE" \
    /repo/scripts/host-capability.py init-keys --state-dir /state
}

install_producer_capability() {
  HOST_STATE_DIR="${SPACEWORKS_HOST_STATE_DIR:-/var/lib/spaceworks/host}"
  grep -E '^BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY=' "$ROOT/.env" | \
    docker run --rm -i --user 0:0 --entrypoint python \
    -v "$ROOT/scripts:/installed-scripts:ro" \
    -v "$HOST_STATE_DIR:/state" "$HOST_CONFIG_IMAGE" \
    /app/scripts/install_producer_capability.py \
    --marker /state/public/producer-capability.json \
    --scripts-dir /installed-scripts --entrypoint /app/scripts/spaceworks_entrypoint.py \
    --migrations-dir /app/apps
}

configure_setup_stripe() {
  SETUP_STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" \
  SETUP_STRIPE_WEBHOOK_SECRET="$STRIPE_WEBHOOK_SECRET" \
  SETUP_STRIPE_DEFAULT_CURRENCY="$STRIPE_DEFAULT_CURRENCY" \
  SETUP_MAKERSPACE_NAME="$MSNAME" \
  "${COMPOSE[@]}" run --rm --no-deps -T \
    -e SETUP_STRIPE_SECRET_KEY -e SETUP_STRIPE_WEBHOOK_SECRET \
    -e SETUP_STRIPE_DEFAULT_CURRENCY -e SETUP_MAKERSPACE_NAME \
    backend --role management python manage.py shell -c '
import os
from django.utils.text import slugify
from apps.makerspaces.models import Makerspace
from apps.payments.models import MakerspacePaymentSettings
makerspace = Makerspace.objects.get(slug=slugify(os.environ["SETUP_MAKERSPACE_NAME"]))
settings = MakerspacePaymentSettings.for_makerspace(makerspace)
settings.set_stripe_secret_key(os.environ["SETUP_STRIPE_SECRET_KEY"])
settings.set_stripe_webhook_secret(os.environ["SETUP_STRIPE_WEBHOOK_SECRET"])
settings.default_currency = os.environ["SETUP_STRIPE_DEFAULT_CURRENCY"]
settings.save()
'
}
