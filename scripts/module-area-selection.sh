#!/usr/bin/env bash
# The same area catalogue and follow-ups as the initial questionnaire.
source "$(dirname "${BASH_SOURCE[0]}")/setup-question-input.sh"
source "$(dirname "${BASH_SOURCE[0]}")/setup-area-questions.sh"

module_change_one() {
  local slug="$1" output key index input token count=0 original active removals=0
  local states=() selected=() newly=() previous_active=()
  AREA_SETTING_RECORDS=(); AREA_SETTINGS_JSON='{}'; REQUEST_ACCESS=''; AREA_CREATE_PLAN=N
  AREA_CURRENCY_ASKED=0; AREA_root_currency=''
  SETUP_SELECTED_AREAS=''
  # Exact module-key exclusions retain their historical automation semantics.
  if [[ "${MODULE_MODE:-interactive}" == without ]]; then
    module_legacy_change_one "$slug" || return 1
    MODULE_AREAS_APPLIED=1
    return
  fi
  output="$(${COMPOSE[@]+${COMPOSE[@]+"${COMPOSE[@]}"}} run --rm --no-deps -T backend --role management \
    python manage.py apply_setup_areas --makerspace "$slug" --status 2>&1)" || { module_warn "$output"; return 1; }
  AREA_root_currency="$(printf '%s\n' "$output" | sed -n 's/.*"currency": *"\([a-z][a-z][a-z]\)".*/\1/p' | tail -n 1)"
  for key in ${SETUP_AREAS[@]+"${SETUP_AREAS[@]}"}; do
    original="$(printf '%s\n' "$output" | sed -n "s/.*\"$key\": *\"\(on\|partial\|off\)\".*/\1/p" | tail -n 1)"
    [[ -n "$original" ]] || { module_warn 'Could not read current area state.'; return 1; }
    states+=("$original")
    active="$(printf '%s\n' "$output" | sed -n "s/.*\"$key\": *\(true\|false\).*/\1/p" | tail -n 1)"
    if [[ -z "$active" ]]; then [[ "$original" == off ]] && active=false || active=true; fi
    previous_active+=("$active")
    [[ "$original" == off ]] && selected+=(N) || selected+=(Y)
  done
  case "${MODULE_MODE:-interactive}" in
    all) for ((index=0; index<${#selected[@]}; index++)); do selected[index]=Y; done ;;
    areas)
      for ((index=0; index<${#selected[@]}; index++)); do selected[index]=N; done
      local requested=(); IFS=, read -ra requested <<< "${MODULE_AREAS:-}"
      for token in ${requested[@]+"${requested[@]}"}; do
        [[ -n "$token" ]] || continue
        count=0
        for ((index=0; index<${#SETUP_AREAS[@]}; index++)); do
          if [[ "${SETUP_AREAS[index]}" == "$token" ]]; then selected[index]=Y; count=1; fi
        done
        [[ "$count" == 1 ]] || { module_warn "Unknown area '$token'; no changes applied."; return 1; }
      done ;;
    interactive)
      echo 'Choose areas. Each enables all its modules and supported features. Off hides screens and retains data.'
      while :; do
        for ((index=0; index<${#SETUP_AREAS[@]}; index++)); do
          printf '  %d) %s: current %s; selected %s\n' "$((index+1))" "${SETUP_AREA_LABELS[index]}" "${states[index]}" "${selected[index]}"
        done
        read -r -p 'Toggle area numbers, or Enter to review: ' input || return 1
        input="${input%$'\r'}"
        [[ -n "$input" ]] || break
        for token in $input; do
          [[ "$token" =~ ^[1-8]$ ]] || { module_warn "Unknown area number '$token'."; continue; }
          index=$((token-1))
          [[ "${selected[index]}" == Y ]] && selected[index]=N || selected[index]=Y
        done
      done ;;
  esac
  for ((index=0; index<${#SETUP_AREAS[@]}; index++)); do
    key="${SETUP_AREAS[index]}"
    if [[ "${selected[index]}" == Y ]]; then
      SETUP_SELECTED_AREAS+="${SETUP_SELECTED_AREAS:+,}$key"
      [[ "${previous_active[index]}" == true ]] || newly+=("$key")
    elif [[ "${states[index]}" != off ]]; then removals=$((removals+1)); fi
  done
  if [[ "${MODULE_INTERACTIVE:-0}" == 1 ]]; then
    exec 3<&0
    for key in ${newly[@]+"${newly[@]}"}; do "ask_${key}_settings" || return 1; done
    # Membership admission is asked when newly enabled; its borrow rule also applies
    # when Inventory is newly enabled on a space already running memberships.
    if [[ ",${SETUP_SELECTED_AREAS}," == *,inventory,* && ",${SETUP_SELECTED_AREAS}," == *,membership,* && -n "$REQUEST_ACCESS" ]]; then
      echo 'Membership enabled: borrow requests require active members.'
      REQUEST_ACCESS=members
    fi
    build_area_settings_json
    derive_setup_edition
    setup_areas_summary
    echo '  Deployment labels follow all makerspaces on this server; changing the edition restarts application services.'
    local confirm
    question confirm 'Apply these areas and settings?' Y choices:Y,y,yes,YES,N,n,no,NO || return 1
    exec 3<&-
    area_yes "$confirm" || { echo 'Cancelled; no changes applied.'; return 0; }
  fi
  module_confirm_removals "$slug" "$removals" || return 1
  if [[ -n "${MODULE_WITHOUT:-}" ]]; then
    # --without never requires removal acknowledgement for a key already off.
    module_list_output "$slug" || return 1
    local without_keys=() disabled=0 key_count
    IFS=, read -ra without_keys <<< "$MODULE_WITHOUT"
    for key in ${without_keys[@]+"${without_keys[@]}"}; do
      key_count="$(printf '%s\n' "$MODULE_OUTPUT" | awk -v wanted="$key" '$1 == "+" && $2 == wanted {print 1}')"
      [[ "$key_count" != 1 ]] || disabled=$((disabled+1))
    done
    module_confirm_removals "$slug" "$disabled" || return 1
  fi
  # Configure only newly enabled areas; existing settings and feature switches stay.
  local configuring='[' comma=''
  for key in ${newly[@]+"${newly[@]}"}; do configuring+="$comma\"$key\""; comma=,; done
  configuring+=']'
  local document
  document="$(setup_areas_json)"
  document="${document%\}} ,\"configure_areas\":$configuring}"
  printf '%s\n' "$document" | ${COMPOSE[@]+${COMPOSE[@]+"${COMPOSE[@]}"}} run --rm --no-deps -T backend --role management \
    python manage.py apply_setup_areas --makerspace "$slug" --answers-json - \
    || { module_warn "Area changes failed for $slug; transaction rolled back."; return 1; }
  MODULE_AREAS_APPLIED=1
  echo 'Areas applied; module data is retained. Adjust settings later in the staff console.'
}

module_refresh_edition() {
  [[ -f "$ROOT/.env" ]] || return 0
  local edition current temporary
  edition="$(${COMPOSE[@]+${COMPOSE[@]+"${COMPOSE[@]}"}} run --rm --no-deps -T backend --role management \
    python manage.py apply_setup_areas --deployment-edition)" || return 1
  edition="$(printf '%s\n' "$edition" | tr -d '\r' | tail -n 1)"
  case "$edition" in makerspace|events|bookings|organization) ;; *) module_warn 'Could not derive deployment edition.'; return 1 ;; esac
  current="$(repository_env_value SPACEWORKS_EDITION)"; current="${current:-makerspace}"
  [[ "$edition" != "$current" ]] || return 0
  temporary="$(mktemp "$ROOT/.area-edition.XXXXXX")" || return 1
  sed '/^SPACEWORKS_EDITION=/d' "$ROOT/.env" > "$temporary"
  printf '\nSPACEWORKS_EDITION=%s\n' "$edition" >> "$temporary"
  chmod 600 "$temporary"; mv -f -- "$temporary" "$ROOT/.env"
  local OPS_HOST_DIR="${OPS_DIR:-${SPACEWORKS_OPS_HOST_DIR:-/var/lib/spaceworks/ops}}"
  # Same tag fallbacks as scripts/spaceworks-compose.sh: environment, .env, the
  # pinned version marker, then latest (a bash setup.sh install has no marker).
  local tag="${MAKERSPACE_IMAGE_TAG:-$(repository_env_value MAKERSPACE_IMAGE_TAG)}" HOST_CONFIG_IMAGE
  if [[ -z "$tag" && -f "$ROOT/.spaceworks-version" ]]; then tag="$(tr -d '[:space:]' < "$ROOT/.spaceworks-version")"; fi
  tag="${tag:-latest}"
  HOST_CONFIG_IMAGE="${MAKERSPACE_BACKEND_IMAGE:-ghcr.io/spaceworks-hq/spaceworks-backend}:$tag"
  source "$ROOT/scripts/setup-host-orchestration.sh"
  refresh_compose_config || { module_warn 'Areas applied; edition configuration refresh failed. Run bash scripts/init-host-orchestration.sh, then scripts/spaceworks-compose.sh bundled up -d.'; return 1; }
  ${COMPOSE[@]+${COMPOSE[@]+"${COMPOSE[@]}"}} up -d || { module_warn 'Edition saved; application restart failed. Run scripts/spaceworks-compose.sh bundled up -d.'; return 1; }
  say "Deployment edition changed to $edition."
}
