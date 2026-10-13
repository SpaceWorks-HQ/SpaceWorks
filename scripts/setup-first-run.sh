#!/usr/bin/env bash
# Sourced only after the deployment questionnaire has been confirmed.
FIRST_RUN=0
if [[ -f .env ]]; then
  say 'Found an existing .env - keeping your settings and secrets.'
  [[ "${ANSWERS_CONFIRMED:-}" != yes ]] || FIRST_RUN=1
else
  FIRST_RUN=1
  source "$ROOT/scripts/setup-write-environment.sh"
  write_setup_environment
fi
