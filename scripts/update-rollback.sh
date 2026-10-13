#!/usr/bin/env bash
# Failed image deployment leaves forward migrations in place; never restore data here.
rollback_application_images() {
  [[ "$previous_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-main\.[0-9]+\.[0-9a-f]{12}$ ]] || return 0
  say "Update failed; rolling application containers back to $previous_version."
  export MAKERSPACE_IMAGE_TAG="$previous_version"
  printf '%s\n' "$previous_version" > "$VERSION_FILE" || \
    say "WARNING: could not reset $VERSION_FILE to $previous_version."
  "${COMPOSE[@]}" pull "${IMAGE_SERVICES[@]}" || \
    say "Could not refresh previous images; trying the host's cached copies."
  HOST_CONFIG_IMAGE="$MAKERSPACE_BACKEND_IMAGE:$previous_version"
  install_producer_capability || say "Could not refresh the previous producer proof."
  # --no-deps prevents old migrations from being applied to the forward schema.
  if "${COMPOSE[@]}" up -d --no-deps "${ROLLBACK_SERVICES[@]}" && wait_for_backend; then
    say "Rollback complete: $previous_version is healthy."
    cleanup_run_once_jobs || warn "Could not remove finished rollback jobs."
    say "Database changes remain; backup retained at backups/$backup_name."
  else
    say "ERROR: automatic rollback to $previous_version failed."
    say "Restore backups/$backup_name and the previous image tag manually."
  fi
}
