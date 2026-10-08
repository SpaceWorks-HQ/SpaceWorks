# Cloud completeness — build plan for step (2)

This plan works from `00-audit.md` and covers what I build in this lane, in order. Each
group gets its own commit, and its tests land in the same commit. The order is fixed: tests
first, then the smallest change that turns them green. **No module keys and no
migrations.** Any item marked "owner" in audit §18 is out of scope and is listed again in
the final report.

## G1 — Outbound fail-safe fixes (audit §0.2, §0.3, §0.8, §0.9, §12b, §13)

Code changes:

- **`apps/integrations/dispatch.py`:** import `PiiWriteFenced` and
  `assert_mapped_write_allowed` before the `try`. A failing quota lookup then falls into the
  existing `except Exception` and is logged, and the mail still goes out.
- **`apps/makerspaces/limits_reservations.py`:** move `resource_limit` inside the existing
  `try`. That `try` already fails open.
- **Header secret comparisons switch to `django.utils.crypto.constant_time_compare`.** It
  encodes both sides, so a non-ASCII header is a plain mismatch rather than a `TypeError`.
  - `cron_views.py`
  - `integrations/views.py` (Telegram webhook)
  - `payments/providers/razorpay.py`
- **`api_key_request_views.py`:** a non-integer `?makerspace=` returns 400 instead of 500.

New tests:

- `tests/test_managed_quota_check_fail_open.py`
- `tests/test_channel_provider_failures.py`, the full matrix of HTTP status and socket error
  across all five chat/webhook channels, plus a check that the token never appears in logs
- `tests/test_notification_requeue_action.py`
- `tests/test_apiclient_failure_modes.py`
- `tests/test_header_secret_compare.py`, covering the cron, Telegram and Razorpay non-ASCII
  cases and the `api-key-requests` 400

**Risk:** `razorpay.py` belongs to the payments app, so it may be a merge hotspot. The edit
is one line.

## G2 — HTTPS redirect exemption for internal probes (audit §0.1)

Code change, in `config/settings.py`:

```python
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/", r"^api/v1/internal/", r"^api/v1/metrics/$"]
```

It is always set and only takes effect when the redirect is on. These paths are either
blocked at the edge (`/internal/`) or are probes that the edge proxy already serves over TLS.
Exempting them does not weaken any external surface.

Tests, in `tests/test_https_probe_exemption.py`:

- A plain-HTTP request to readiness, tls-check and metrics is served rather than redirected,
  with `SECURE_SSL_REDIRECT=True`.
- A normal API path is still redirected.
- A subprocess that imports settings with `ENABLE_HTTPS=true` sees the redirect on, HSTS set
  and secure cookies set.

## G3 — Live stream robustness (audit §0.4, §10)

Code change in `apps/operations/views_live.py`:

- A misconfigured URL, or Redis being down at subscribe time, returns 503.
- A Redis error mid-stream ends the stream cleanly with a final retry hint, rather than
  raising inside the generator.
- `pubsub.close()` runs in a `finally`.

New tests in `tests/test_live_stream.py`.

## G4 — Updates: stale RUNNING and honest audit (audit §0.5, §8)

Code changes:

- **`apps/updates/services.claim_update`:** a RUNNING row seen at claim time is stale by
  construction, because claim only runs under the host lock. Mark it FAILED with "The
  previous update was interrupted before it finished.", then apply the normal claim rules.
- **`views_platform_updates.PlatformUpdateRequestView`:** record `meta={"noop": true}` when
  the request lands on a RUNNING update.
- **`scripts/update.sh`:**
  - Write `.spaceworks-version` only after `update_control complete` succeeds.
  - Bound the GitHub query with `--max-time 30 --retry 2`.
- **Docs:** `UpdateState` becomes `PlatformUpdateSettings` in `docs/MODULES.md` and
  `docs/PROJECT-STATUS.md`.

Tests:

- New tests in `tests/test_platform_updates.py`.
- Space Manager and anonymous actor cases.
- The module-off PATCH case in `tests/modules/test_offstate_platform.py`.

## G5 — Integration-health parity (audit §0.6, §12c, §17)

Backend change in `apps/integrations/health.py`. `legacy_channels` becomes a per-channel
object `{configured, failed, last_failure, last_sent_at}`, counted over
`destination__isnull=True` rows. That keeps it backward-compatible in meaning. The panel is
its only consumer; the generated types treat the response as untyped JSON.

Frontend change in `IntegrationHealthPanel.tsx`:

- Render a "Chat & webhook rooms" block.
- Each room shows Not configured / Inactive / failed count / last failure.
- Legacy channels are shown the same way.

Tests:

- New cases in `tests/test_integration_health.py`.
- `IntegrationHealthPanel.test.tsx`, including an axe check.

## G6 — `/control/` audit entries for platform integration admins (audit §0.12, §11g)

Add `save_model` / `delete_model` that call `apps.audit.services.record` to:

- PlatformEmailSettings
- PlatformSmsSettings
- PlatformPushSettings
- the social settings, login methods and OIDC provider admins
- PlatformUpdateSettings

The metadata names the changed fields only, never their values.

Test in `tests/test_control_integration_audit.py`.

`payments/admin.py` (MakerspacePaymentSettings) is left to the payments lane. It is a
hotspot, and audit §11g lists it.

## G7 — Social settings API lockout guard (audit §0.13)

`PlatformSocialAuthSettingsSerializer.validate` reuses the `/control/` form's lockout
predicate, so the two surfaces refuse the same edits. Tests sit beside the existing form
tests.

## G8 — OpenAPI error responses (audit §15)

- Add shared `ERROR_RESPONSES` helpers in `apps/openapi.py`.
- Document the error responses on every in-scope operation listed in audit §15.
- Declare the missing tags.

Test: `tests/test_cloud_openapi_errors.py` generates the schema and asserts that every
in-scope operation documents at least one 4xx.

Then regenerate `frontend/openapi-schema.json` and `frontend/src/generated/api.ts`.

## G9 — Environment surface (audit §0.7, §16)

- Pass `METRICS_TOKEN`, `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` and `SENTRY_ENVIRONMENT`
  through `docker-compose.prod.yml` (on the backend anchor) and `docker-compose.cloud.yml`,
  using blank defaults.
- Add `docs/environment-reference.md`, which lists every `ENV_SURFACE` name grouped by
  area, with its default and purpose.
- Add a drift test asserting that every `ENV_SURFACE` name appears in that doc.
- Add `docker-compose.cloud.yml` to `PRODUCTION_MANIFESTS` only if it already satisfies the
  guards. Otherwise, list it.

## G10 — Scheduler honesty (audit §9)

- `run_scheduled_tasks --task <unknown>` raises `CommandError`.
- Rename the misleading `test_a_failed_task_is_still_due_next_run` to say what it actually
  checks.

## Defaults I am choosing (the owner may reverse any of them)

- **Probe exemption:** exempt rather than turning `SECURE_SSL_REDIRECT` off in the overlays.
  The edge still redirects browsers.
- **Stale RUNNING:** becomes FAILED rather than a new status, so there is no migration and
  the console's existing "Update failed" path shows it.
- **Health payload:** grows in place rather than getting a versioned new key.

## Not built here (owner or out of lane)

Everything in audit §18. In addition:

- SMS, FCM/APNs and JWKS provider-failure tests. These are worthwhile but large. They are
  next in line if time remains, starting with `tests/test_sms_twilio.py`.
- The OIDC unlink route.
- Push false-SENT labelling.
- `platform_email_configured` treating an unreadable password as configured.

## Outcome (2026-10-09, end of lane)

G1–G10 are built, each with its own tests (see `LANE-PROGRESS.md` for commits and runs).

After the plan, these were also built:

- **Twilio, FCM, JWKS and DNS failure matrices.** Two JWKS 500s were fixed along the way: an
  array body, and a mid-body read failure.
- **`platform_email_configured`** now treats an unreadable password as unconfigured.
- **OIDC unlink** works.
- **Archived-domain TLS/host tests** were added.
- **Probe 503 tests** were added.
- **A read-only `PeriodicTaskRun` page** was added to `/control/`.
- **Connect webhook signature tests** were added.

Still not built:

- **Push false-SENT labelling.** Changing it alters delivery counts, so it needs an owner
  decision.
- **APNs provider tests.** The sender uses an httpx HTTP/2 client and was not reached.
- **A behavioural test for `update.sh`.**
- **CI for the tombstone suite.**
- **Everything in audit §18.**
