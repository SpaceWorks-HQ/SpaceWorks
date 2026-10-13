#!/usr/bin/env bash
# Sourced after readiness succeeds. Never discard running or failed jobs.
cleanup_run_once_jobs() {
  local service cid state
  for service in orchestration-init migrate orchestration-ready createbuckets; do
    cid="$("${COMPOSE[@]}" ps -a -q "$service")" || return 1
    [[ -n "$cid" ]] || continue
    state="$(docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' "$cid")" || return 1
    [[ "$state" == 'exited 0' ]] || {
      printf 'Keeping %s for inspection (state: %s).\n' "$service" "$state" >&2
      return 1
    }
  done
  "${COMPOSE[@]}" rm -f -s orchestration-init migrate orchestration-ready createbuckets
}
