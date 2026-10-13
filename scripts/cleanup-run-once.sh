#!/usr/bin/env bash
# Sourced after readiness succeeds. Never discard running or failed jobs.
cleanup_run_once_jobs() {
  local service cid state
  source "${UPDATE_SCRIPT_DIR:-${RESTORE_SCRIPT_DIR:-$ROOT/scripts}}/compose-deployment.sh"
  deployment_services
  for service in "${RUN_ONCE_SERVICES[@]}"; do
    cid="$("${COMPOSE[@]}" ps -a -q "$service")" || return 1
    [[ -n "$cid" ]] || continue
    state="$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$cid")" || return 1
    [[ "$state" == 'exited 0' ]] || {
      printf 'Keeping %s for inspection (state: %s).\n' "$service" "$state" >&2
      return 1
    }
  done
  "${COMPOSE[@]}" rm -f -s "${RUN_ONCE_SERVICES[@]}"
}
