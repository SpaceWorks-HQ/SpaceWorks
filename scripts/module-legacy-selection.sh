#!/usr/bin/env bash
# Compatibility for module-key --without automation. No interactive module prompts.
module_legacy_change_one() {
  local slug="$1" raw line mark rest key desc i input tok pass changed=0 removals=0 apply_failed=0
  local result without_key found
  local keys=() descs=() state=() orig=() without=()
  module_list_output "$slug" || return 1
  raw="$MODULE_OUTPUT"
  while IFS= read -r line; do
    case "$line" in
      "  + "*|"  - "*)
        mark="${line:2:1}"; rest="${line:4}"; key="${rest%% *}"
        desc="${rest#"$key"}"; desc="${desc#"${desc%%[![:space:]]*}"}"
        keys+=("$key"); descs+=("$desc")
        [[ "$mark" == + ]] && state+=(x) || state+=(" ")
        ;;
    esac
  done <<< "$raw"
  ((${#keys[@]} > 0)) || {
    say "No optional modules are available for $slug; core modules remain on."
    return 0
  }
  orig=(${state[@]+"${state[@]}"})

  if [[ "${MODULE_MODE:-interactive}" == all ]]; then
    for ((i=0; i<${#state[@]}; i++)); do state[i]=x; done
  fi
  if [[ -n "${MODULE_WITHOUT:-}" ]]; then
    IFS=, read -r -a without <<< "$MODULE_WITHOUT"
    for without_key in ${without[@]+"${without[@]}"}; do
      [[ -n "$without_key" ]] || continue
      found=0
      for ((i=0; i<${#keys[@]}; i++)); do
        if [[ "${keys[i]}" == "$without_key" ]]; then state[i]=" "; found=1; break; fi
      done
      [[ "$found" == 1 ]] || { module_warn "Unknown or core module '$without_key'; no changes were applied to $slug."; return 1; }
    done
  fi

  # A preceding question may already have implied a module. `setup.sh` asks who may
  # submit borrow requests, and the answer IS the `membership` module -- so the tick list
  # opens with it already ticked (or unticked) rather than making the operator work out
  # the connection themselves. Applied BEFORE the interactive loop on purpose: they can
  # still see it and change their mind, and whatever they leave ticked is what gets
  # applied. Nothing here decides the final state; the DB read-back after apply does.
  module_apply_forced_state() {
    local list="$1" want="$2" key j
    [[ -n "$list" ]] || return 0
    local forced=()
    IFS=, read -r -a forced <<< "$list"
    for key in ${forced[@]+"${forced[@]}"}; do
      [[ -n "$key" ]] || continue
      for ((j=0; j<${#keys[@]}; j++)); do
        if [[ "${keys[j]}" == "$key" ]]; then state[j]="$want"; break; fi
      done
    done
  }
  module_apply_forced_state "${MODULE_FORCE_ON:-}" x
  module_apply_forced_state "${MODULE_FORCE_OFF:-}" " "

  for ((i=0; i<${#keys[@]}; i++)); do
    [[ "${orig[$i]}" == x && "${state[$i]}" != x ]] && removals=$((removals + 1))
  done
  module_confirm_removals "$slug" "$removals" || return 1

  for pass in 1 2; do
    for ((i=0; i<${#keys[@]}; i++)); do
      [[ "${state[$i]}" != "${orig[$i]}" ]] || continue
      if [[ "${state[$i]}" == x ]]; then
        if result="$(${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
          python manage.py install_module "${keys[$i]}" --makerspace "$slug" 2>&1)"; then
          say "Installed ${keys[i]} for $slug."; orig[i]=x; changed=1
        elif [[ "$pass" == 2 ]]; then
          module_warn "Could not install ${keys[$i]} for $slug: $result"
          apply_failed=1
        fi
      else
        if result="$(${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
          python manage.py uninstall_module "${keys[$i]}" --makerspace "$slug" 2>&1)"; then
          say "Disabled ${keys[i]} for $slug; its data is retained."; orig[i]=" "; changed=1
        elif [[ "$pass" == 2 ]]; then
          module_warn "Kept ${keys[$i]} for $slug: $result"
          apply_failed=1
        fi
      fi
    done
  done
  [[ "$changed" == 1 ]] || say "No module changes for $slug."
  echo "Data is never deleted here; only purge_module_data can delete retained module data."
  return "$apply_failed"
}
