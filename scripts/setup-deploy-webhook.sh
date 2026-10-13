#!/usr/bin/env bash
# Small sourced questionnaire helper so other installer lanes can move these questions.
ask_deploy_webhook() {
  local answer
  if [[ "${SPACEWORKS_INSTALL_REPOSITORY_PINNED:-0}" == 1 ]]; then
    printf 'Following GitHub repository selected by installer: %s\n' "$SPACEWORKS_REPOSITORY"
  else
    read -r -p "GitHub repository to follow [${SPACEWORKS_REPOSITORY:-SpaceWorks-HQ/SpaceWorks}]: " answer
    SPACEWORKS_REPOSITORY="${answer:-${SPACEWORKS_REPOSITORY:-SpaceWorks-HQ/SpaceWorks}}"
  fi
  configure_release_repository || die "Invalid GitHub repository."
  read -r -p 'Set up automatic deploys from GitHub releases? [Y/n]: ' answer
  SPACEWORKS_DEPLOY_WEBHOOK_SECRET=""
  if [[ ! "$answer" =~ ^[Nn] ]]; then SPACEWORKS_DEPLOY_WEBHOOK_SECRET="$(rand_key 64)"; fi
  export SPACEWORKS_DEPLOY_WEBHOOK_SECRET
}

finish_deploy_webhook_setup() {
  [[ -n "${SPACEWORKS_DEPLOY_WEBHOOK_SECRET:-}" ]] || return 0
  bash "$ROOT/scripts/install-deploy-webhook.sh" \
    || die "Host trigger installation failed. Run bash scripts/install-deploy-webhook.sh before configuring GitHub."
  printf '\nIn GitHub repository %s: Settings -> Webhooks -> Add webhook\n' "$SPACEWORKS_REPOSITORY"
  printf '  Payload URL: https://%s/hooks/deploy\n' "${WEBHOST:-localhost}"
  printf '  Content type: application/json\n  Secret: %s (save now; shown once)\n' "$SPACEWORKS_DEPLOY_WEBHOOK_SECRET"
  printf '  Let me select individual events -> Releases only\n  Active: checked\n'
  printf 'The server must be reachable from GitHub over HTTPS.\n'
  printf "A fork's own release workflow must have run at least once to publish its images.\n"
}
