#!/usr/bin/env bash
# Remove only the deleted app's token; surviving tombstones keep their exact values.
without_update_tombstone() {
  local value="$1" token trimmed result="" separator=""
  local tokens=()
  IFS=',' read -r -a tokens <<< "$value"
  for token in "${tokens[@]}"; do
    trimmed="$(printf '%s' "$token" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [[ "$trimmed" != updates ]] || continue
    result+="$separator$token"
    separator=,
  done
  printf '%s' "$result"
}

retire_update_tombstone() {
  local file="${SPACEWORKS_STATIC_ENV_FILE:-$ROOT/.env}" value cleaned temporary
  if [[ -f "$file" ]]; then
    value="$(repository_env_value TOMBSTONED_APPS)"
    cleaned="$(without_update_tombstone "$value")"
    if [[ "$value" != "$cleaned" ]]; then
      temporary="$(mktemp "$(dirname "$file")/.retired-app-env.XXXXXX")"
      sed '/^TOMBSTONED_APPS=/d' "$file" > "$temporary"
      printf '\nTOMBSTONED_APPS=%s\n' "$cleaned" >> "$temporary"
      chmod 600 "$temporary"
      mv -f -- "$temporary" "$file"
    fi
  fi
  if [[ "${TOMBSTONED_APPS+x}" == x ]]; then
    export TOMBSTONED_APPS="$(without_update_tombstone "$TOMBSTONED_APPS")"
  fi
}
