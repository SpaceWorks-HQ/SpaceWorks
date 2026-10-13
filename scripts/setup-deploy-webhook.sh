#!/usr/bin/env bash
# Sourced after the confirmed deployment questions.
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
