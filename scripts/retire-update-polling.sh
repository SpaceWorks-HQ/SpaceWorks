#!/usr/bin/env bash
# Retire former automatic-update triggers on upgraded hosts, preserving other jobs:
# the weekly polling cron (<= 0.9.0) and the 0.9.1 deploy-webhook trigger (a systemd
# path/service pair, or a one-minute cron on hosts without systemd). Deploys now come
# only from the self-hosted runner's release job or a manual update.sh run.
retire_update_polling() {
  local existing filtered unit_dir privileged=()
  if command -v crontab >/dev/null 2>&1; then
    existing="$(crontab -l 2>/dev/null || true)"
    filtered="$(printf '%s\n' "$existing" | grep -v -F '# Space Works automatic production update' \
      | grep -v -F "$ROOT/scripts/update.sh" | grep -v -F "$ROOT/scripts/deploy-from-request.sh" || true)"
    if [[ "$existing" != "$filtered" ]]; then printf '%s\n' "$filtered" | crontab -; fi
  fi
  unit_dir="${SPACEWORKS_SYSTEMD_DIR:-/etc/systemd/system}"
  [[ -e "$unit_dir/spaceworks-deploy.path" || -e "$unit_dir/spaceworks-deploy.service" ]] || return 0
  command -v systemctl >/dev/null 2>&1 || return 0
  [[ "$(id -u)" == 0 ]] || privileged=(sudo -n)
  if ((${#privileged[@]})) && ! sudo -n true 2>/dev/null; then
    warn "The retired deploy-webhook units are still installed. Remove them with: sudo systemctl disable --now spaceworks-deploy.path spaceworks-deploy.service && sudo rm $unit_dir/spaceworks-deploy.path $unit_dir/spaceworks-deploy.service && sudo systemctl daemon-reload"
    return 0
  fi
  ${privileged[@]+"${privileged[@]}"} systemctl disable --now spaceworks-deploy.path spaceworks-deploy.service >/dev/null 2>&1 || true
  ${privileged[@]+"${privileged[@]}"} rm -f "$unit_dir/spaceworks-deploy.path" "$unit_dir/spaceworks-deploy.service"
  ${privileged[@]+"${privileged[@]}"} systemctl daemon-reload >/dev/null 2>&1 || true
  say "Retired the former deploy-webhook trigger; deploys now come from the GitHub Actions runner."
}
