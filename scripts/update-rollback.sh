#!/usr/bin/env bash
# Sourced by update.sh; the web only records restore intent. Never execute a new SQL path.
privileged_update_rollback() {
  command -v sudo >/dev/null 2>&1 \
    || die "Rollback needs root access to private host state. Install sudo and rerun this update as the install owner."
  command -v flock >/dev/null 2>&1 || die "Rollback requires the Linux restore supervisor and flock."
  # Retain the parent's portable lock; the root child takes operation.lock itself.
  flock -u 8
  exec 8>&-
  sudo env SPACEWORKS_OPS_HOST_DIR="$OPS_DIR" \
    SPACEWORKS_HOST_STATE_DIR="${SPACEWORKS_HOST_STATE_DIR:-/var/lib/spaceworks/host}" \
    SPACEWORKS_UPDATE_INSTALL_DIR="$ROOT" \
    SPACEWORKS_COMPOSE_LAYER="${SPACEWORKS_COMPOSE_LAYER:-}" \
    SPACEWORKS_COMPOSE_BUILD_LAYER="${SPACEWORKS_COMPOSE_BUILD_LAYER:-0}" \
    SPACEWORKS_STATIC_ENV_FILE="${SPACEWORKS_STATIC_ENV_FILE:-$ROOT/.env}" \
    MAKERSPACE_BACKEND_IMAGE="${MAKERSPACE_BACKEND_IMAGE:-ghcr.io/spaceworks-hq/spaceworks-backend}" \
    BACKUP_AGE_IDENTITY_FILE="${BACKUP_AGE_IDENTITY_FILE:-$OPS_DIR/work/age-identity.txt}" \
    MAKERSPACE_IMAGE_TAG="${MAKERSPACE_IMAGE_TAG:-}" \
    bash "${UPDATE_SCRIPT_DIR:-$ROOT/scripts}/update-rollback-host.sh" "$1" \
    || die "The privileged rollback refused or paused. Inspect the restore stage in Platform settings, then rerun bash scripts/update.sh --no-module-changes."
  exit 0
}

handle_update_rollback() {
  local plan rollback_version restore_id metadata stage temporary_intent
  local intent="$OPS_DIR/update-rollback.intent"
  if [[ "$(uname -s)" == Linux && "$(id -u)" != 0 && -e "$intent" ]]; then
    [[ "$APP_SERVICE" == backend ]] || die "The existing restore supervisor requires the bundled topology; rollback remains queued."
    privileged_update_rollback resume
  fi
  if [[ -e "$intent" ]]; then
    [[ -f "$intent" && ! -L "$intent" && "$(stat -c %u "$intent")" == "$(id -u)" \
      && "$(stat -c %a "$intent")" == 600 ]] || die "The rollback intent is not a private host-owned file."
    plan="$(cat "$intent")"
  elif [[ -n "${HOST_ROLLBACK_PLAN:-}" && "$HOST_ROLLBACK_PLAN" != resume ]]; then
    plan="$HOST_ROLLBACK_PLAN"
  else
    plan="$(${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
      python manage.py update_control rollback-plan | tr -d '\r' | tail -n 1)" \
      || die "Could not check pending update rollback."
  fi
  [[ "$plan" != none ]] || return 0
  read -r rollback_version restore_id <<< "$plan"
  [[ "$rollback_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ \
    && "$restore_id" =~ ^[0-9a-f-]{36}$ ]] || die "Invalid update rollback plan."
  [[ "$APP_SERVICE" == backend ]] \
    || die "The existing restore supervisor requires the bundled topology; rollback remains queued."
  if [[ "$(uname -s)" == Linux && "$(id -u)" != 0 ]]; then
    privileged_update_rollback "$plan"
  fi
  command -v flock >/dev/null 2>&1 \
    || die "Rollback requires the Linux/WSL2 restore supervisor."
  if [[ ! -e "$intent" ]]; then
    # This file lives outside the application-writable work mount. Keep it across
    # database replacement, which removes the singleton's rollback pointer.
    temporary_intent="$(mktemp "$OPS_DIR/.update-rollback-XXXXXXXX")"
    chmod 600 "$temporary_intent"
    printf '%s %s\n' "$rollback_version" "$restore_id" > "$temporary_intent"
    sync -f "$temporary_intent"
    mv -f -- "$temporary_intent" "$intent"
    sync -f "$OPS_DIR"
  fi
  metadata="$(MAKERSPACE_IMAGE_TAG="$rollback_version" ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
    python manage.py backup_control describe "$restore_id" | tail -n 1 || true)"
  stage="$(printf '%s' "$metadata" | sed -n 's/.*"stage": "\([a-z_]*\)".*/\1/p')"
  say "Restoring the pre-update snapshot and release $rollback_version. Review the restore diff in the console."
  # The existing supervisor takes operation.lock itself. Retain the portable update
  # lock to exclude another updater, but release this descriptor before the handoff.
  flock -u 8
  exec 8>&-
  if [[ "$stage" != completed && "$stage" != restored_quarantined && "$stage" != aborted && "$stage" != failed ]]; then
    if ! bash "${UPDATE_SCRIPT_DIR:-$ROOT/scripts}/restore.sh" "$restore_id" "--update-image=$rollback_version"; then
      die "Rollback supervisor refused or paused the restore; inspect its persisted stage before retrying."
    fi
  fi
  exec 8>"$OPS_DIR/operation.lock"
  flock -n 8 || die "Another host operation started after restore; retain the current version marker."
  metadata="$(MAKERSPACE_IMAGE_TAG="$rollback_version" ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
    python manage.py backup_control describe "$restore_id" | tail -n 1)"
  stage="$(printf '%s' "$metadata" | sed -n 's/.*"stage": "\([a-z_]*\)".*/\1/p')"
  if [[ "$stage" == completed || "$stage" == restored_quarantined ]]; then
    # Restore replaced the database; select the matching application images without
    # invoking migrate (which would immediately re-apply the upgrade's migrations).
    export MAKERSPACE_IMAGE_TAG="$rollback_version"
    printf '%s\n' "$rollback_version" > "$VERSION_FILE"
    local restored_services=(backend live)
    source "${UPDATE_SCRIPT_DIR:-$ROOT/scripts}/compose-deployment.sh"
    [[ "$(deployment_value SPACEWORKS_RUN_FRONTEND)" == no ]] || restored_services+=(frontend)
    ${COMPOSE[@]+"${COMPOSE[@]}"} up -d --no-deps "${restored_services[@]}"
    if [[ "$stage" == completed ]]; then
      ${COMPOSE[@]+"${COMPOSE[@]}"} up -d --no-deps worker beat
      wait_for_backend || die "The restored release is not ready."
      ${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
        python manage.py update_control complete --version "$rollback_version" >/dev/null
    fi
    say "Rollback reached $stage at $rollback_version."
  elif [[ "$stage" == aborted || "$stage" == failed ]]; then
    say "Rollback reached $stage; the current version marker was retained."
  else
    die "Rollback has not completed (stage ${stage:-unknown}); retain the current version marker."
  fi
  rm -f -- "$intent"
  sync -f "$OPS_DIR"
  exit 0
}
