#!/usr/bin/env bash
# Retire the former weekly polling cron on upgraded hosts, preserving other jobs.
retire_update_polling() {
  local existing filtered
  command -v crontab >/dev/null 2>&1 || return 0
  existing="$(crontab -l 2>/dev/null || true)"
  filtered="$(printf '%s\n' "$existing" | grep -v -F '# Space Works automatic production update' \
    | grep -v -F "$ROOT/scripts/update.sh" || true)"
  if [[ "$existing" != "$filtered" ]]; then printf '%s\n' "$filtered" | crontab -; fi
}
