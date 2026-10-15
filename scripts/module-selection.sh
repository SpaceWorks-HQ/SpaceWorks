#!/usr/bin/env bash
# Shared registry-backed module selection for setup.sh and scripts/update.sh.

module_warn() { warn "$@"; }

module_list_output() {
  local slug="${1:-}" args=()
  [[ -n "$slug" ]] && args=(--makerspace "$slug")
  MODULE_OUTPUT="$(${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
    python manage.py list_modules ${args[@]+"${args[@]}"} 2>&1)" && return 0
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
    if ! output="$(${COMPOSE[@]+"${COMPOSE[@]}"} run --rm --no-deps -T backend --role management \
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
  answer="${answer%$'\r'}"
  [[ "$answer" == "$slug" ]] || { module_warn "Module removals cancelled; no changes were applied."; return 1; }
}

source "$(dirname "${BASH_SOURCE[0]}")/module-legacy-selection.sh"
source "$(dirname "${BASH_SOURCE[0]}")/module-area-selection.sh"

change_modules() {
  local slug failed=0
  MODULE_AREAS_APPLIED=0
  module_targets || return 1
  for slug in ${MODULE_TARGETS[@]+"${MODULE_TARGETS[@]}"}; do
    module_change_one "$slug" || failed=1
  done
  # Refresh after any committed area change, even if another makerspace failed:
  # the edition must follow what is now in the database.
  if [[ "$MODULE_AREAS_APPLIED" == 1 ]]; then
    module_refresh_edition || failed=1
  fi
  return "$failed"
}
