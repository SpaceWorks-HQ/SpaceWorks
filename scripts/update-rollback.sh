#!/usr/bin/env bash
# Sourced by update.sh; the web only records restore intent. Never execute a new SQL path.
handle_update_rollback() {
  local plan rollback_version restore_id metadata stage temporary_intent
  local intent="$OPS_DIR/update-rollback.intent"
  if [[ -e "$intent" ]]; then
    [[ -f "$intent" && ! -L "$intent" && "$(stat -c %u "$intent")" == "$EUID" \
      && "$(stat -c %a "$intent")" == 600 ]] || die "The rollback intent is not a private host-owned file."
    plan="$(cat "$intent")"
  else
    plan="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py update_control rollback-plan | tr -d '\r' | tail -n 1)" \
      || die "Could not check pending update rollback."
  fi
  [[ "$plan" != none ]] || return 0
  read -r rollback_version restore_id <<< "$plan"
  [[ "$rollback_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-(main|beta)\.[0-9]+\.[0-9a-f]{12}$ \
    && "$restore_id" =~ ^[0-9a-f-]{36}$ ]] || die "Invalid update rollback plan."
  [[ "$APP_SERVICE" == backend ]] \
    || die "The existing restore supervisor requires the bundled topology; rollback remains queued."
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
  metadata="$(MAKERSPACE_IMAGE_TAG="$rollback_version" "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py backup_control describe "$restore_id" | tail -n 1 || true)"
  stage="$(printf '%s' "$metadata" | sed -n 's/.*"stage": "\([a-z_]*\)".*/\1/p')"
  say "Restoring the pre-update snapshot and release $rollback_version. Review the restore diff in the console."
  # The existing supervisor takes operation.lock itself. Retain the portable update
  # lock to exclude another updater, but release this descriptor before the handoff.
  flock -u 8
  exec 8>&-
  if [[ "$stage" != completed && "$stage" != restored_quarantined && "$stage" != aborted && "$stage" != failed ]]; then
    if ! bash "$ROOT/scripts/restore.sh" "$restore_id" "--update-image=$rollback_version"; then
      die "Rollback supervisor refused or paused the restore; inspect its persisted stage before retrying."
    fi
  fi
  exec 8>"$OPS_DIR/operation.lock"
  flock -n 8 || die "Another host operation started after restore; retain the current version marker."
  metadata="$(MAKERSPACE_IMAGE_TAG="$rollback_version" "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py backup_control describe "$restore_id" | tail -n 1)"
  stage="$(printf '%s' "$metadata" | sed -n 's/.*"stage": "\([a-z_]*\)".*/\1/p')"
  if [[ "$stage" == completed || "$stage" == restored_quarantined ]]; then
    # Restore replaced the database; select the matching application images without
    # invoking migrate (which would immediately re-apply the upgrade's migrations).
    export MAKERSPACE_IMAGE_TAG="$rollback_version"
    printf '%s\n' "$rollback_version" > "$VERSION_FILE"
    "${COMPOSE[@]}" up -d --no-deps backend frontend
    if [[ "$stage" == completed ]]; then
      "${COMPOSE[@]}" up -d --no-deps worker beat
      wait_for_backend || die "The restored release is not ready."
      "${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
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
