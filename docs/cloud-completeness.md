# Cloud completeness continuation

The cloud lane's audit and plan are in the main checkout's
`docs/plans/2026-10-09-cloud-completeness/`. This continuation closes conditions that
can be reproduced locally, without a paid provider account. Database tests must be
run by the coordinator using the isolated test runner; no database results are claimed
for this continuation.

## Provider failures and observability

- FCM and APNs classify unreadable credentials and malformed response objects as
  provider failures. A malformed refusal cannot invalidate a device token. FCM only
  recognizes an exact structured `UNREGISTERED` code or `NOT_FOUND` status.
- OIDC token exchange bounds body size and elapsed read time, translates streamed
  socket/protocol failures into provider unavailability, and closes responses on every
  exit. Discovery and JWKS caches are optional: cache failures trigger fresh fetches,
  with all issuer, audience, nonce and signature validation retained. JWKS entries must
  be objects; unusable signing keys are rejected.
- Apple accepts the literal nonce or its SHA-256 digest. Unicode nonce mismatches are
  ordinary identity failures. Local tests cover this without Apple credentials.
- A failed live-stream subscription closes its allocated pubsub connection. Existing
  stream-drop and disconnect cleanup remain in place.
- SMTP queue failures and scheduler errors retain the exception class, not exception
  text that may contain a credential or connection URL. Health subsection errors use
  the same sanitized class-only diagnostic.

## Audit and console surfaces

- Domain edits audit the previous and next domain inside the existing row-locked DRF
  update transaction. No-op edits emit no additional domain-change event.
- The tenant payment `/control/` save still uses the credential-validation service.
  It now records `payments.settings_updated` in the same transaction; metadata contains
  changed field names only. This file is a coordinator merge hotspot with the payments
  lane; provider selection and payment workflows are unchanged.
- `PeriodicTaskRun` is registered as a global, read-only, superadmin-only control page.
  The sidebar links it and the existing SMS, push, social, login-method and OIDC admins.
- Health reports effective SMTP credentials, including platform fallback, and each
  chat room uses the delivery path's own credential predicate. SMS configuration and
  scoped native-push last failures appear in the staff console. Push delivery accounting
  semantics remain the existing ones pending the owner decision below.
- Platform email, social and Connect panels label absent configuration. The email log
  filters skipped rows and shows why they were skipped. Cached health remains server
  state in TanStack Query, refreshed by its existing interval and window-focus policy.
- OpenAPI now includes social/phone/OIDC/push/config errors, live 403, and the expanded
  health fields. The coordinator regenerates the schema snapshot and generated types.

## Environment and host operations

`settings_policy.ENV_SURFACE` and `docs/environment-reference.md` both describe exactly
247 backend names. No new environment setting or migration is needed. The three env
examples expose the metrics/Sentry opt-ins and point to that complete reference.
`test_env_surface_drift.py` covers cloud and all backend services, including cron and
the single-box app. The overlay guard evaluates SaaS/TLS/single layers over the production
base and pins the managed suffix on migrate, worker and beat.

The bundled updater follows the same environment/build/persisted-layer precedence as
the Compose wrapper. Single-box readiness targets the running `app`, and image pulls
include `app`. Management commands still run through the standard backend image and its
explicit management-role entrypoint; the all-in-one image is a supervisor, so running
management commands as its container command would start the supervisor instead.
Local behavioral tests pin success, provider/pull failures, rollback, marker recovery,
no-op, persisted single-box choice and lock handling. GHCR tests pin bounded retries and
deletion refusal after malformed or unavailable listings.

## Owner decisions and external validation still outstanding

The audit's section 18 remains the owner-decision list. This continuation does not change
proxy/client-IP topology, HSTS defaults, host-allowlist outage policy, probe access policy,
rate-limit policy, live reauthorization/routing, module-off contracts, identity gating or
credential rotation. It does not add updater status values, release publication gates,
beat/cron coordination, or tombstone CI profiles.

Apple client-secret generation/revocation requires the owner's Apple developer account.
Real test-send endpoints and persisted platform delivery/check outcomes for SMTP, SMS,
FCM/APNs and Stripe remain audit section 18.17. Local transport tests do not establish
that a real account, quota or deployed provider credential works. Native push's existing
SENT result for no eligible device remains a separate owner decision in the plan.

An outside-lane defect remains in
`tests/test_host_orchestration_surface_h1a.py`: its `/usr/bin/python3` stub may not exist
in the backend image. The earlier session reported that failure; it was not rerun here.
Codex CLI review is unavailable in this sandbox because `codex doctor` cannot resolve its
configuration or reach the provider. The coordinator must complete review and execution
of the test inventory recorded in `LANE-PROGRESS.md`.
