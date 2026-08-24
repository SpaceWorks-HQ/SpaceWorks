#!/usr/bin/env bash
# Portable updater lock. Uses host flock when available and a crash-recoverable
# PID/timestamp directory lock for Git Bash hosts where flock is unavailable.

acquire_update_lock() {
  local now owner_pid="" owner_started="" age="unknown"
  now="$(date +%s)"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [[ -f "$LOCK_DIR/owner" ]]; then
      read -r owner_pid owner_started < "$LOCK_DIR/owner" || true
    elif [[ -f "$LOCK_DIR/pid" ]]; then
      owner_pid="$(tr -dc '0-9' < "$LOCK_DIR/pid")"
    fi
    if [[ "$owner_started" =~ ^[0-9]+$ && "$now" -ge "$owner_started" ]]; then
      age="$((now - owner_started))s"
    fi
    if [[ "$owner_pid" =~ ^[0-9]+$ ]] && kill -0 "$owner_pid" 2>/dev/null; then
      if [[ "${UPDATE_LOCK_OVERRIDE:-0}" != 1 ]]; then
        die "Another update owns $LOCK_DIR (PID $owner_pid, age $age). If that PID is unrelated or wedged, verify it first, then rerun with --override-lock."
      fi
      say "Overriding the update lock owned by live PID $owner_pid (age $age) at operator request."
    elif [[ "$owner_pid" =~ ^[0-9]+$ ]]; then
      say "Recovering the stale update lock left by dead PID $owner_pid (age $age)."
    elif [[ "${UPDATE_LOCK_OVERRIDE:-0}" == 1 ]]; then
      say "Overriding an unreadable update lock at operator request."
    else
      die "The existing update lock has no readable owner. Inspect $LOCK_DIR, then rerun with --override-lock if no update is active."
    fi
    rm -f -- "$LOCK_DIR/owner" "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || die "Could not clear $LOCK_DIR; it contains unexpected files."
    mkdir "$LOCK_DIR"
  fi
  printf '%s %s\n' "$$" "$now" > "$LOCK_DIR/owner"
  UPDATE_LOCK_HELD=1

  mkdir -p "$OPS_DIR"
  if command -v flock >/dev/null 2>&1; then
    exec 8>"$OPS_DIR/operation.lock"
    flock -n 8 || die "Another backup, restore, verification, or update is running."
  else
    say "Host flock is unavailable; using the PID/timestamp update lock. Dead owners are recovered automatically; use --override-lock only after verifying no update is active."
  fi
}

release_update_lock() {
  local owner_pid=""
  [[ "${UPDATE_LOCK_HELD:-0}" == 1 ]] || return 0
  if [[ -f "$LOCK_DIR/owner" ]]; then
    read -r owner_pid _ < "$LOCK_DIR/owner" || true
  fi
  if [[ "$owner_pid" == "$$" ]]; then
    rm -f -- "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" 2>/dev/null || true
  fi
  UPDATE_LOCK_HELD=0
}
