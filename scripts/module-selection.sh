#!/usr/bin/env bash
# Shared registry-backed module selection for setup.sh and scripts/update.sh.

module_warn() { warn "$@"; }

module_list_output() {
  local slug="${1:-}" args=()
  [[ -n "$slug" ]] && args=(--makerspace "$slug")
  MODULE_OUTPUT="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
    python manage.py list_modules "${args[@]}" 2>&1)" && return 0
  case "$MODULE_OUTPUT" in
    *"More than one makerspace exists; pass --makerspace <slug>."*) return 2 ;;
    *"No makerspaces exist yet."*)
      module_warn "No makerspace exists yet; create one before changing modules."
      ;;
    *"No makerspace with slug"*) module_warn "$MODULE_OUTPUT" ;;
    *"Cannot connect"*|*"connection refused"*|*"Is the docker daemon running"*|*"no such service"*)
      module_warn "The backend is unreachable, so its live module registry could not be read."
      module_warn "$MODULE_OUTPUT"
      ;;
    *)
      module_warn "The backend command failed while reading the live module registry:"
      module_warn "$MODULE_OUTPUT"
      ;;
  esac
  return 1
}

module_targets() {
  local output slug
  MODULE_TARGETS=()
  if [[ "${MODULE_ALL_MAKERSPACES:-0}" == 1 ]]; then
    if ! output="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
      python manage.py shell -c \
      'from apps.makerspaces.models import Makerspace; [print(f"SPACEWORKS_MAKERSPACE:{slug}") for slug in Makerspace.objects.order_by("id").values_list("slug", flat=True)]' 2>&1)"; then
      module_warn "The backend is unreachable, so makerspaces could not be listed."
      module_warn "$output"
      return 1
    fi
    while IFS= read -r slug; do
      [[ "$slug" == SPACEWORKS_MAKERSPACE:* ]] || continue
      slug="${slug#SPACEWORKS_MAKERSPACE:}"
      [[ "$slug" =~ ^[A-Za-z0-9_-]+$ ]] && MODULE_TARGETS+=("$slug")
    done <<< "$output"
    ((${#MODULE_TARGETS[@]} > 0)) || {
      module_warn "No makerspaces exist yet; create one before changing modules."
      return 1
    }
    return 0
  fi

  if [[ -n "${MODULE_MAKERSPACE:-}" ]]; then
    module_list_output "$MODULE_MAKERSPACE" || return 1
  else
    module_list_output "" || {
      local list_status=$?
      if [[ "$list_status" == 2 ]]; then
        if [[ "${MODULE_INTERACTIVE:-0}" != 1 ]]; then
          module_warn "More than one makerspace exists; pass --makerspace <slug> or explicitly use --all-makerspaces."
          return 1
        fi
        read -r -p "Makerspace slug to change: " MODULE_MAKERSPACE
        [[ -n "$MODULE_MAKERSPACE" ]] || { module_warn "No makerspace selected."; return 1; }
        module_list_output "$MODULE_MAKERSPACE" || return 1
      else
        return 1
      fi
    }
  fi
  slug="$(printf '%s\n' "$MODULE_OUTPUT" | sed -n 's/^Modules for \([^:]*\):$/\1/p' | head -n 1)"
  [[ -n "$slug" ]] || { module_warn "The module command returned no makerspace identity."; return 1; }
  MODULE_TARGETS=("$slug")
}

module_confirm_removals() {
  local slug="$1" count="$2" answer
  ((count > 0)) || return 0
  if [[ "${MODULE_CONFIRM_REMOVALS:-0}" == 1 ]]; then
    say "Confirmed: disabling $count module(s) for $slug; retained data will not be purged."
    return 0
  fi
  if [[ "${MODULE_INTERACTIVE:-0}" != 1 ]]; then
    module_warn "Disabling $count module(s) for $slug requires --confirm-removals. No changes were applied."
    return 1
  fi
  echo "Disabling modules hides their screens but retains all of their data."
  read -r -p "Type '$slug' to confirm these removals: " answer
  [[ "$answer" == "$slug" ]] || { module_warn "Module removals cancelled; no changes were applied."; return 1; }
}

module_change_one() {
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
  orig=("${state[@]}")

  if [[ "${MODULE_MODE:-interactive}" == all ]]; then
    for ((i=0; i<${#state[@]}; i++)); do state[i]=x; done
  fi
  if [[ -n "${MODULE_WITHOUT:-}" ]]; then
    IFS=, read -r -a without <<< "$MODULE_WITHOUT"
    for without_key in "${without[@]}"; do
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
    for key in "${forced[@]}"; do
      [[ -n "$key" ]] || continue
      for ((j=0; j<${#keys[@]}; j++)); do
        if [[ "${keys[j]}" == "$key" ]]; then state[j]="$want"; break; fi
      done
    done
  }
  module_apply_forced_state "${MODULE_FORCE_ON:-}" x
  module_apply_forced_state "${MODULE_FORCE_OFF:-}" " "

  if [[ "${MODULE_MODE:-interactive}" == interactive ]]; then
    say "Choose modules for $slug"
    echo "Ticked modules are enabled. Core modules are always on."
    echo "Presets: a = all optional modules, n = core only. Numbers toggle individual modules."
    while :; do
      echo
      for ((i=0; i<${#keys[@]}; i++)); do
        printf '  [%s] %2d) %-20s %s\n' "${state[$i]}" "$((i + 1))" "${keys[$i]}" "${descs[$i]}"
      done
      read -r -p "Toggle (numbers, a, n, or Enter to apply): " input || input=""
      [[ -n "$input" ]] || break
      case "$input" in
        a|A) for ((i=0; i<${#state[@]}; i++)); do state[i]=x; done; continue ;;
        n|N) for ((i=0; i<${#state[@]}; i++)); do state[i]=" "; done; continue ;;
      esac
      for tok in $input; do
        [[ "$tok" =~ ^[0-9]+$ ]] || { module_warn "'$tok' is not a number."; continue; }
        i=$((tok - 1))
        ((i >= 0 && i < ${#keys[@]})) || { module_warn "$tok is out of range."; continue; }
        [[ "${state[i]}" == x ]] && state[i]=" " || state[i]=x
      done
    done
  fi

  for ((i=0; i<${#keys[@]}; i++)); do
    [[ "${orig[$i]}" == x && "${state[$i]}" != x ]] && removals=$((removals + 1))
  done
  module_confirm_removals "$slug" "$removals" || return 1

  for pass in 1 2; do
    for ((i=0; i<${#keys[@]}; i++)); do
      [[ "${state[$i]}" != "${orig[$i]}" ]] || continue
      if [[ "${state[$i]}" == x ]]; then
        if result="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
          python manage.py install_module "${keys[$i]}" --makerspace "$slug" 2>&1)"; then
          say "Installed ${keys[i]} for $slug."; orig[i]=x; changed=1
        elif [[ "$pass" == 2 ]]; then
          module_warn "Could not install ${keys[$i]} for $slug: $result"
          apply_failed=1
        fi
      else
        if result="$("${COMPOSE[@]}" run --rm --no-deps -T backend --role management \
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

change_modules() {
  local slug failed=0
  module_targets || return 1
  for slug in "${MODULE_TARGETS[@]}"; do
    module_change_one "$slug" || failed=1
  done
  return "$failed"
}
