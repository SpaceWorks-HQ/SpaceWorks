#!/usr/bin/env bash
# A pinned installer stages new host tooling separately from private installation state.
# Copy only the runtime bundle after the database backup; preserve every replaced file.
install_staged_host_bundle() {
  local source_root="$1" destination backup relative temporary
  [[ "$source_root" != "$ROOT" ]] || return 0
  backup="$ROOT/backups/host-config-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  HOST_CONFIG_BACKUP_DIR="$backup"
  local files=(
    setup.sh install.sh setup.ps1
    docker-compose.prod.yml docker-compose.cloud.yml
    docker/compose.build.yml docker/compose.single.yml docker/compose.tls.yml docker/compose.saas.yml
    deploy/Caddyfile deploy/Caddyfile.saas frontend/nginx.conf
    backend/scripts/deploy_webhook.py
    scripts/bundled-database-url.py scripts/cleanup-run-once.sh scripts/configure-compose-wrapper.py
    scripts/deploy-from-request.sh scripts/host-capability.py scripts/import-backup.sh
    scripts/init-host-orchestration.sh scripts/install-deploy-webhook.sh scripts/install-host-bundle.sh
    scripts/install-owner.sh scripts/module-selection.sh scripts/restore.sh scripts/retire-update-polling.sh scripts/retire-update-tombstone.sh
    scripts/select-main-release.py scripts/setup-deploy-webhook.sh scripts/setup-first-run.sh
    scripts/setup-host-orchestration.sh scripts/spaceworks-compose.sh scripts/spaceworks-repository.sh
    scripts/update-lock.sh scripts/update.ps1 scripts/update.sh scripts/validate-compose-wrapper.py
  )
  # Refuse incomplete archives before replacing any file.
  for relative in "${files[@]}"; do
    [[ -f "$source_root/$relative" ]] || die "The pinned archive lacks $relative."
  done
  mkdir -p "$ROOT/backups"
  chmod 700 "$ROOT/backups"
  for relative in "${files[@]}"; do
    destination="$ROOT/$relative"
    mkdir -p "$(dirname "$destination")" "$(dirname "$backup/$relative")"
    [[ ! -f "$destination" ]] || cp -p "$destination" "$backup/$relative"
    temporary="$(mktemp "$(dirname "$destination")/.deploy-bundle.XXXXXX")"
    cp -p "$source_root/$relative" "$temporary"
    mv -f -- "$temporary" "$destination"
  done
  for relative in scripts/install-auto-update.sh scripts/install-auto-update.ps1 \
    scripts/update-rollback.sh scripts/update-rollback-host.sh scripts/filter-main-releases.py; do
    if [[ -f "$ROOT/$relative" ]]; then
      mkdir -p "$(dirname "$backup/$relative")"
      mv -- "$ROOT/$relative" "$backup/$relative"
    fi
  done
  say "Installed pinned host runtime files; previous files are in $backup."
}
