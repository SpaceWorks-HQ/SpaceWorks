# Cloud completeness audit — "online cloud services, all conditions"

Lane `cloud`, branch `lane/cloud`, forked from `dev` at `b7c2ee93` on 2026-10-09. This is a
read-only audit of every surface that makes a SpaceWorks deployment reachable and connected
online.

> **Where this file lives.** The brief asked for
> `docs/plans/2026-10-09-cloud-completeness/` in the main checkout. This worktree-isolated
> session was refused write access outside its worktree, so the file is committed at
> `LANE-CLOUD-AUDIT/` on the lane branch instead. Move it into `docs/plans/` (which is
> gitignored) and drop this directory when the lane is squashed.

Paths are relative to the repo root, and `tests/` means `backend/tests/`. Every test ID was
confirmed by grep at `b7c2ee93`; none was inferred from a file name.

**Status legend**

| Code | Meaning |
|---|---|
| **BT** | Built and tested |
| **BU** | Built, but no test |
| **M** | Missing |
| **BUG** | Built, and wrong |
| **T(local)** | A test exists, but CI never runs it |

**Two caveats apply to the whole document.**

- **The tombstone suite never runs in CI.** `tests/tombstone/conftest.py:37-41` skips its
  files unless `TOMBSTONED_APPS` equals the profile, and neither `.github/workflows/tests.yml`
  nor `scripts/dev.sh` sets it. Every "app tombstoned" cell below that cites
  `tests/tombstone/` is therefore T(local).
- **No host shell script has a behavioural test.** `update.sh`, `update-lock.sh`,
  `install-auto-update.sh` and `verify-release-images.sh` are pinned only by assertions on
  their source text:
  - `tests/test_platform_updates.py::test_the_host_script_is_the_thing_that_drives_docker`
  - `tests/test_host_orchestration_surface_h1a.py::test_bundled_host_scripts_route_management_commands_through_explicit_role`

---

## 0. Highest-value findings (ranked)

1. **BUG — `ENABLE_HTTPS=true` redirects every plain-HTTP internal caller.** Django answers
   301 and points them at `https://`.
   - **Callers affected:**
     - the Caddy on-demand TLS ask;
     - every compose healthcheck (`urllib.urlopen` follows the redirect onto a TLS-less port
       and fails);
     - Prometheus.
   - **Why it happens:** no `SECURE_REDIRECT_EXEMPT` exists.
   - **Stacks affected:** `docker/compose.saas.yml:33`, `docker/compose.tls.yml:4` and
     `docker-compose.cloud.yml:84` (which defaults to true).
   - **Consequence on the SaaS overlay:** custom-domain certificates are never issued, and
     the backend never reports healthy.
   - **Evidence:** `backend/config/settings.py:945`; `deploy/Caddyfile.saas:4`;
     `docker-compose.cloud.yml:186,220`; `docker-compose.prod.yml:184,321`.
2. **BUG — two managed-quota checks fail loudly instead of failing open.**
   - **`dispatch_email`:** it imports `PiiWriteFenced` *inside* the `try` that its own
     `except PiiWriteFenced` guards. Any failure before that import raises
     `UnboundLocalError` out of the mail path, instead of the intended logged fail-open. One
     such failure is the `resource_limit` lookup on a `/control/`-stored
     `{"email": "abc"}`. Reproduced: the new test fails exactly this way before the fix.
   - **`reserve_notification_quota`:** it calls `resource_limit` outside its `try`, so the
     same failure drops the whole channel fan-out with no log row.
   - **Evidence:** `backend/apps/integrations/dispatch.py:99-143`;
     `backend/apps/makerspaces/limits_reservations.py:15`; `limits_core.py:69`.
3. **BUG — secrets read from headers are compared in a way that crashes.** The code calls
   `hmac/secrets.compare_digest(str, str)`, which raises `TypeError` (and so a 500) on any
   non-ASCII header byte.
   - **Affected endpoints:** the cron endpoint, the Telegram webhook, and the Razorpay
     webhook signature.
   - **Consequence:** a stranger can make each of them answer 500 at will, which also makes
     Razorpay retry.
   - **Evidence:** `backend/apps/hardware_requests/cron_views.py:46`;
     `backend/apps/integrations/views.py:130`; `backend/apps/payments/providers/razorpay.py:167`.
4. **BUG — the live stream has three robustness faults.**
   - A misconfigured `LIVE_REDIS_URL` becomes a 500, because the Redis client is built
     outside the view's `try`.
   - A Redis outage mid-stream raises inside the generator (`get_message` is unguarded) and
     cuts the stream.
   - The pubsub connection is never closed.
   - **Evidence:** `backend/apps/operations/views_live.py:44-56,97-106`;
     `backend/apps/operations/live.py:43-51`.
5. **M — an interrupted update can never recover.** If the host is killed mid-update,
   `PlatformUpdateSettings.status` stays `RUNNING` forever. `claim_update` never recovers it,
   and the console disables both controls while `RUNNING`. `claim` only runs under the host
   lock, so any `RUNNING` it sees is stale by construction.
   - **Evidence:** `backend/apps/updates/services.py:27-53`;
     `frontend/src/features/staff/PlatformUpdatePanel.tsx:100,140`.
6. **M (console parity) — chat delivery failures are never shown.** The backend already
   reports per-room "failed / last failure" in `chat_destinations`, but the staff console's
   Integration-health panel never renders it. Failed legacy (destination-less) chat
   deliveries are reported nowhere at all.
   - **Evidence:** `frontend/src/features/staff/IntegrationHealthPanel.tsx:18-45` has no
     `chat_destinations` key; `backend/apps/integrations/health.py:106-180`, where
     `legacy_channels` is only a configured/not-configured boolean.
7. **BUG (env surface) — metrics and Sentry cannot be switched on under Docker.**
   `METRICS_TOKEN`, `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` and `SENTRY_ENVIRONMENT` are
   documented, but no compose file passes them to the backend and none uses `env_file`. Both
   features can only be enabled by editing the YAML.
   - **Evidence:** `docs/self-hosting.md:334-335`; `docker-compose.prod.yml:120-180`;
     `docker-compose.cloud.yml:60-120`.
8. **BU — the dead-letter path has no test.**
   `NotificationDeliveryLogAdmin.requeue_failed_deliveries` is the only way to re-queue a
   failed chat or webhook delivery, and nothing tests it.
   - **Evidence:** `backend/apps/integrations/admin_notifications.py:42-61`;
     `grep -rl requeue backend/tests` returns nothing.
9. **BUG — a non-numeric filter crashes the key-request list.**
   `GET /api/v1/admin/api-key-requests?makerspace=abc` builds
   `filter(makerspace_id="abc")`, which raises `ValueError` and returns 500.
   - **Evidence:** `backend/apps/admin_api/api_key_request_views.py:30-32`.
10. **M (OpenAPI) — error responses are undocumented.** 151 of the 612 schema operations
    document no 4xx/5xx response at all. The in-scope ones are listed in §15.
11. **M (env docs) — most settings are documented nowhere.** Of the 247 `ENV_SURFACE` names,
    112 appear in no env example **and** no doc, and 167 appear in no doc. Details in §16.
12. **M (audit) — `/control/` edits to platform integrations leave no audit row.** Edits to
    platform SMS, push, login methods, social, OIDC, platform email and per-makerspace
    payment settings write only Django's `LogEntry` and never `apps.audit.services.record`.
    See §11.
13. **BUG (lockout) — the social-settings API skips the lockout guard.**
    `PATCH /admin/platform/social-auth-settings` does not apply the guard that the
    `/control/` form enforces. Clearing a provider's client ID through the API can strand
    users whose only credential is that provider.
    - **Evidence:** `backend/apps/admin_api/views_platform_social.py:31-48` vs.
      `backend/apps/accounts/admin_social.py:36-62`.
14. **Doc drift — the updates model is misnamed.** `docs/MODULES.md:525` and
    `docs/PROJECT-STATUS.md:51` call it `UpdateState`; it is `PlatformUpdateSettings`
    (`backend/apps/updates/models.py:4`).

---

## 1. Managed SaaS vs self-host

### 1a. Mode detection

| Condition | Code | Tests | Status |
|---|---|---|---|
| Self-host (suffix blank or whitespace) | `apps/makerspaces/domain_verification.py:17-21`; `config/settings.py:43-60` | `tests/test_domain_verification.py::test_whitespace_suffix_is_treated_as_self_host` | BT |
| Suffix normalisation (leading dot) | `settings.py:43-55` | `tests/test_domain_verification.py::test_platform_suffix_normalization_prepends_leading_dot` | BT |
| Managed mode without `BEHIND_TRUSTED_PROXY` (fixed `ALLOWED_HOSTS` then rejects every custom domain) | `settings.py:26,71-72` — no guard | — | M (owner) |
| Worker, beat or migrate started without the suffix behave as self-host and auto-verify domains | `apps/makerspaces/apps.py:27-39`; only mitigated by `docker/compose.saas.yml:45-55` | — | BU |
| `BEHIND_TRUSTED_PROXY` sets `ALLOWED_HOSTS=["*"]`, so self-host has no host validation | `settings.py:71-72` | — | BU (owner) |

### 1b. Host middleware and the verified-host cache

| Condition | Code | Tests | Status |
|---|---|---|---|
| Self-host passes everything through | `apps/makerspaces/middleware.py:11-12` | `tests/test_saas_hosting.py::test_host_validation_middleware_is_passthrough_when_suffix_blank`; `tests/test_domain_verification.py::test_middleware_passes_through_on_whitespace_suffix` | BT |
| Managed: unknown host → 400; infra host passes | `middleware.py:13-15`; `hosting.py:40-49` | `tests/test_saas_hosting.py::test_host_validation_middleware_rejects_unknown_and_passes_infra` | BT |
| Managed: verified custom domain admitted at the middleware level | `hosting.py:80` | Only the set is tested: `tests/test_saas_hosting.py::test_verified_domains_only_includes_verified` | BU |
| Archived or not-restored tenant dropped from the allowlist | `hosting.py:58` | — | BU |
| Cache, DB or Redis outage → fail closed | `hosting.py:81-82` | `tests/test_saas_hosting.py::test_host_is_allowed_fails_closed` | BT |
| Redis present vs absent (Redis cache vs DatabaseCache fallback) | `settings.py:464-519` | — | BU |
| Cache invalidated on save and delete | `apps.py:21-25,66-89` | `tests/test_frontend_domain.py::test_selfhost_verified_domains_cache_reflects_create_and_clear` | BT (self-host path only) |
| A queryset `.update()` skips invalidation (stale for the implicit 300 s TTL) | `hosting.py:65`; `apps/tenant_migration/cutover.py:142` | — | BU |

### 1c. Setting a custom domain (`PATCH /api/v1/admin/makerspaces/{id}`)

| Condition / actor | Code | Tests | Status |
|---|---|---|---|
| Self-host superadmin → VERIFIED immediately | `apps/admin_api/serializers_makerspace_mutations.py:145-165` | `tests/test_frontend_domain.py::test_selfhost_superadmin_patch_domain_verifies_and_trusts_origin`, `::test_selfhost_direct_create_with_domain_is_auto_verified`, `::test_selfhost_reconcile_promotes_preexisting_pending_row_on_save` | BT |
| Self-host Space Manager → 400 | `serializers_makerspace_domain.py:46-57` | `tests/test_frontend_domain.py::test_selfhost_non_superadmin_cannot_set_domain`, `::test_selfhost_self_governed_space_manager_still_cannot_set_domain`, `::test_selfhost_update_rechecks_superadmin_gate_under_row_lock`, `::test_selfhost_non_superadmin_noop_domain_patch_is_allowed` | BT |
| Managed Space Manager: no grant → 400; with override → PENDING | `serializers_makerspace_domain.py:72-91` | `tests/test_managed_limits_enforcement.py::test_managed_tenant_custom_domain_blocked_without_grant`, `::test_managed_tenant_custom_domain_allowed_with_override`; `tests/test_frontend_domain.py::test_managed_patch_custom_domain_stays_pending` | BT |
| Claiming a platform subdomain or the apex → 400 | `serializers_makerspace_domain.py:58-71` | `tests/test_saas_hosting.py::test_tenant_makerspace_update_rejects_platform_subdomain`, `::test_serializer_rejects_platform_apex`, `::test_serializer_rejects_platform_subdomain_claim` | BT |
| Domain-change cooldown | `serializers_makerspace_domain.py:25-30` | `tests/test_saas_hosting.py::test_domain_change_cooldown_rejects_a_second_change`, `::test_domain_change_is_allowed_after_cooldown_passes`, `::test_domain_change_cooldown_is_dormant_when_zero` | BT |
| Duplicate domain; clearing the domain | `serializers_makerspace_domain.py:92-102` | `tests/test_frontend_domain.py::test_serializer_rejects_duplicate_frontend_domain_case_insensitively`; `tests/test_domain_verification.py::test_clearing_frontend_domain_resets_status_and_record` | BT |
| A domain-specific audit entry with before and after values | Only the generic `makerspace.updated` exists (`views_makerspaces.py:130-135`) | — | M |

### 1d. DNS TXT verification (`POST .../verify-domain`)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Token present → VERIFIED; legacy `_osmm-verify` label accepted | `domain_verification.py:175-190,10-11,160` | `tests/test_domain_verification.py::test_verify_domain_marks_verified_when_token_present`, `::test_verify_domain_accepts_legacy_osmm_txt_label` | BT |
| Token absent → FAILED | `:192-198` | `::test_verify_domain_marks_failed_when_token_absent`, `::test_managed_custom_domain_without_txt_fails` | BT |
| Resolver outage → FAILED "DNS lookup failed", audited, HTTP 200 | `:160-173`; `views_domain_verification.py:55-61` | `tests/test_domain_verification.py::test_verify_endpoint_handles_resolver_error_and_audits` | BT |
| Resolver timeout (5 s), malformed non-UTF-8 answer, or one label erroring while the other holds the token | `:36-40,160-166` | Covered only through the generic catch | BU |
| TXT matches but origin does not; both match; origin unset | `:176-183` | `tests/test_saas_hosting.py::test_verify_domain_fails_when_txt_matches_but_origin_does_not`, `::test_verify_domain_succeeds_when_txt_and_origin_match`, `::test_verify_domain_keeps_legacy_txt_only_behavior_when_origin_is_blank` | BT |
| The real `resolves_to_origin` logic (CNAME, A-record overlap, NoAnswer) | `:45-73` | Always monkeypatched | BU |
| Self-host auto-VERIFIED; platform subdomain skips lookup; concurrent domain change aborts | `:24-31,138-156,96-119` | `::test_selfhost_domain_is_trusted_without_txt`; `tests/test_saas_hosting.py::test_verify_domain_platform_subdomain_stays_verified`, `::test_verify_domain_aborts_on_concurrent_domain_change` | BT |
| Actors: Inventory Manager 403; other space 404; hidden or archived 404 | `views_domain_verification.py:44-53` | `tests/test_domain_verification.py::test_verify_endpoint_manage_makerspace_gating` | BT |
| Rate limit (the DNS lookup is synchronous, about 25 s worst case) | none | — | M (owner) |

### 1e. Subdomain request and provisioning

| Condition | Code | Tests | Status |
|---|---|---|---|
| Provision: superadmin 200, Space Manager 403; reserved label, multi-label and collision refused | `apps/admin_api/views_hosting.py:94-118`; `apps/makerspaces/provisioning.py:42-46,81-82` | `tests/test_saas_hosting.py::test_provision_subdomain_endpoint_requires_superadmin`, `::test_provision_subdomain_rejects_reserved_label`, `::test_provision_subdomain_rejects_multi_label`, `::test_provision_subdomain_rejects_case_insensitive_collision`, `::test_provision_subdomain_sets_verified_platform_domain` | BT |
| Self-host → "not enabled"; invalid suffix | `provisioning.py:39-40,50-55` | — | BU |
| Request lifecycle: create, self-host reject, second pending, cross-space, invalid, taken, trim, scoping | `views_subdomain_requests.py:74-126` | Nine tests in `tests/test_subdomain_requests.py` | BT |
| `makerspace.subdomain_requested` audit entry | `views_subdomain_requests.py:116-122` | Not asserted | BU |
| `/control/` approve and reject (rollback, skip, audit) | `apps/makerspaces/admin_subdomains.py:38-138` | Five tests in `tests/test_subdomain_approval.py` | BT |
| On self-host, `endswith("")` is always true, giving a misleading admin error | `admin_subdomains.py:57-62` | — | BUG (minor) |

### 1f. Caddy on-demand TLS ask (`GET /api/v1/internal/tls-check`)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Verified custom domain → 200; pending, platform or invalid → 403; lookup error → 403; denials are non-enumerable | `views_hosting.py:59-71` | Six tests in `tests/test_saas_hosting.py` (`test_tls_check_*`) | BT |
| Archived tenant's domain → 403 | — | — | BU |
| `ENABLE_HTTPS=true` answers the plain-HTTP ask with a 301 | §0.1 | — | **BUG** |
| Blocked at the public edge | `deploy/Caddyfile.saas:11-13`; `frontend/nginx.conf:16-18`; **not** in `deploy/Caddyfile:4` | — | BU (owner) |

## 2. HTTPS, TLS and CSP

| Condition | Code | Tests | Status |
|---|---|---|---|
| Plain-HTTP dev: all TLS hardening off | `settings.py:940-961` | `tests/test_usec.py::test_tls_hardening_defaults_off_for_http_docker_deployment` | BT |
| `ENABLE_HTTPS=true` turns on the redirect, Secure cookies, and HSTS (1 year, includeSubDomains, preload) | `settings.py:945-956` | — | BU |
| Internal probes exempt from the redirect | none | — | **BUG** (§0.1) |
| `TRUST_X_FORWARDED_PROTO` sets `SECURE_PROXY_SSL_HEADER` | `settings.py:941-944` | Only checks the variable is present in manifests: `tests/test_env_surface_drift.py::test_the_proxy_posture_is_explicit_in_every_production_manifest` | BU |
| Global CSP is strict; `/control/` gets unsafe-eval and the S3 img-src | `settings.py:968-981`; `config/admin_access_csp.py:12-37` | Four tests in `tests/test_admin_access.py` and `tests/test_admin_monitoring.py` | BT |
| Social-login CSP: unchanged when dormant, exact when configured | `apps/accounts/social_csp.py` | `tests/accounts/test_social_auth.py::test_social_csp_is_unchanged_when_dormant_and_exact_when_configured` | BT |
| The SPA served by nginx carries no CSP, HSTS, X-Frame-Options or nosniff headers | `frontend/nginx.conf:74-76` | — | M (owner) |

## 3. Trusted proxies and client IP

| Condition | Code | Tests | Status |
|---|---|---|---|
| Production with `TRUSTED_PROXY_COUNT` unset → `ImproperlyConfigured` | `settings.py:28-33` | `tests/test_throttle_proxy.py::test_production_settings_refuse_an_unset_proxy_count` | BT |
| DEBUG defaults to 0; count 1 takes the client from XFF; count 0 ignores a spoofed XFF | `settings.py:38-40,317,932`; `config/client_ip.py:9-15` | Three tests in `tests/test_throttle_proxy.py` | BT |
| Negative count; axes and DRF counts disagree | `settings.py:34-35`; `client_ip.py:11-14` | — | BU |
| Every production manifest declares its proxy posture | — | Covers `render.yaml`, `docker-compose.prod.yml` and `deploy/render.managed.yaml` only — **not** `docker-compose.cloud.yml` or the overlays | BT (partial) |
| SaaS chain Cloudflare → Caddy → backend: throttles key on Cloudflare edge IPs (no `trusted_proxies` in `Caddyfile.saas`) | `deploy/Caddyfile.saas`; `docker-compose.prod.yml:151` | — | M (owner) |

## 4. Health, readiness and metrics

| Condition | Code | Tests | Status |
|---|---|---|---|
| `/health/` answers 200, including during quarantine | `apps/operations/views_health.py:10-16`; `apps/backup/route_policy.py:5-7` | Two tests in `tests/backup/test_recovery_gate.py` | BT |
| DB down: the recovery gate returns 503 on every route, liveness included | `apps/backup/middleware.py:28-31` | — | BU (owner) |
| An invalid bearer token on a probe → 401 (JWT authentication is not disabled) | `views_health.py:10-12,19-21` | — | BU |
| Readiness answers 200 and includes custody counts | `views_health.py:35-44` | `tests/backup/test_host_readiness_h1a.py::test_readiness_is_reachable_during_quarantine`; `tests/backup/test_archive_custody_reporting.py::test_readiness_counts_below_floor_custody_rows` | BT |
| Readiness checks fail (marker, OID, migrations, fences) | `apps/backup/host_readiness.py:76-113` | Six unit tests | BT at unit level; the HTTP 503 is BU |
| Metrics: no token → 404; wrong token → 401; `X-Metrics-Token` → 200; documented in the schema | `views_metrics.py:159-166` | Four tests in `tests/test_metrics_endpoint.py` | BT |
| Metrics via `Authorization: Bearer`; broker unreachable → empty gauge | `views_metrics.py:135-139,56-61` | — | BU |
| Metrics settings passed through compose | — | — | **BUG** (§0.7) |

## 5. Sentry opt-in

| Condition | Code | Tests | Status |
|---|---|---|---|
| Unset → the SDK is never imported | `settings.py:1136-1137` | — | BU |
| Set → Django and Celery integrations, `send_default_pii=False`, traces sample rate 0.0 | `settings.py:1138-1148` | — | BU |
| Sentry settings passed through compose | — | — | **BUG** (§0.7) |
| Events tagged with the request ID, or scrubbed in `before_send` | none | — | M (owner) |

## 6. Request-ID logging

| Condition | Code | Tests | Status |
|---|---|---|---|
| Valid header honoured and echoed; unsafe value replaced; missing header minted; unbound when the view raises | `config/request_id.py:41-63` | Four tests in `tests/test_request_id.py` | BT |
| Celery publish and rebind; JSON formatter; settings wiring | `config/celery_signals.py:19-50`; `config/log_setup.py:29-88` | Three tests in `tests/test_request_id.py`; four in `tests/test_log_setup.py` | BT |
| `X-Request-ID` readable by cross-origin JavaScript | No `CORS_EXPOSE_HEADERS` | — | M (owner) |

## 7. Internal cron (`CRON_SECRET`)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Unset → 404; wrong or missing → 403; correct → 200; archived and hidden spaces skipped | `apps/hardware_requests/cron_views.py:40-49` | Three tests in `tests/test_cron_return_reminders.py` | BT |
| Non-ASCII header → `TypeError` → 500 | `cron_views.py:46` | — | **BUG** (§0.3) |
| Reachability: the docs say to call it externally, but nginx and `Caddyfile.saas` block it, while `deploy/Caddyfile` leaves it open | `docs/deploy-production.md:175-185` | — | owner |

## 8. Updates module

What the module consists of:

- **Model:** `PlatformUpdateSettings` (`apps/updates/models.py:4-31`). Its statuses are idle,
  queued, running and failed. There is no rolled-back status and no check-failed status.
- **Services:** `apps/updates/services.py`
  - queue 9-24
  - claim 27-53
  - record_backup 56-64
  - complete 67-78
  - fail 81-90
- **Host CLI:** `update_control` (`management/commands/update_control.py:30-60`).
- **API:** `apps/admin_api/views_platform_updates.py`.
- **There is no in-app release check.** Only the host scripts query GitHub:
  `scripts/update.sh:143-152` and `scripts/update.ps1:61-66`.

| Condition | Code | Tests | Status |
|---|---|---|---|
| Superadmin GET and PATCH the toggle (audited); Update now returns 202 (audited); read-only fields stay read-only | `views_platform_updates.py:46-106` | Three tests in `tests/test_platform_updates.py` | BT |
| Member GET → 403 | `permissions.py:36-41` | Same test | BT |
| Space Manager; member POST; anonymous; API client | Same | — | BU |
| Module off → GET and POST answer 404 (a deliberate 404, see docstring `:15-26`) | `deployment_modules.py:60-62` | `tests/modules/test_offstate_platform.py::test_updates_off_hides_the_updater_but_platform_settings_work_and_on_restores_it` | BT |
| Module off → PATCH 404 | `:71` | — | BU |
| Module off → the host `update_control` still claims, and the `/control/` admin is still editable | No module check | — | BU (owner) |
| App tombstoned → routes, admin and sidebar entry removed | `urls_platform.py:187-199`; `admin.py:40-41` | `tests/tombstone/test_updates_removed_surfaces.py` (6 tests). One of them is vacuous: `::test_the_settings_row_is_still_readable_for_host_side_tooling` asserts `count() >= 0` | T(local) |
| Claim respects the toggle, the queue and `--force` | `services.py:34-46` | Two tests | BT |
| current == available → IDLE | `services.py:47-51` | — | BU |
| Failure is recorded, capped and retriable; full CLI round trip | `services.py:81-90` | Five tests | BT |
| Update now while RUNNING: a silent no-op that still writes `platform.update_requested` | `services.py:12`; `views:97-102` | — | BU (misleading audit) |
| Stale RUNNING after a host crash | none | — | **M** (§0.5) |
| GitHub outage, timeout, 4xx or rate limit | `update.sh:143-146` uses `curl --fail` with no `--max-time`, and records nothing | — | Partial: the check can hang, and the UI never sees the failure |
| `.spaceworks-version` is written before `update_control complete`. If `complete` fails, the containers are rolled back while the marker names the new tag | `update.sh:201-204` | — | BUG |
| Single-box layer: `update.sh:90` execs into `backend`, which `docker/compose.single.yml:12-21` puts behind an inactive profile | `update.sh:90,112,193` | — | Likely BUG |
| Rollback on deploy or readiness failure; the update lock (live PID refused, dead PID recovered, `--override-lock`) | `update.sh:102-127`; `scripts/update-lock.sh:8-42` | — | BU |
| GHCR retention: keeps children and prev/main/latest/sha; a discovery failure vetoes deletion; malformed manifests handled | `scripts/ghcr-retention.py:29-250` | Seven tests in `tests/test_ghcr_retention.py` | BT |
| Retention: listing failure, malformed row, DELETE failure, retry count | `ghcr-retention.py:91-113,143-144,209-249` | — | BU |
| The web process never gets the Docker socket | — | Two tests in `tests/test_platform_updates.py` | BT |

## 9. Scheduler (beat vs beat-less)

| Condition | Code | Tests | Status |
|---|---|---|---|
| The beat schedule and the beat-less runner list the same tasks | `settings.py:579`; `run_scheduled_tasks.py:34` | Four tests in `tests/test_scheduled_tasks.py` | BT |
| Scheduler mode is declared; an external scheduler without a fence is refused | `apps/backup/topology.py:16-55` | Three tests | BT |
| One row per task; `--due-only`; one task's failure is isolated | `run_scheduled_tasks.py:188-228` | Three tests | BT |
| A failed task is retried on the next tick | Not true. `last_run_at` is stamped *before* the work (`:202-204`), so delivery is at-most-once. `::test_a_failed_task_is_still_due_next_run` only checks `is_due` on a hand-made row | — | Misleading test |
| An unknown `--task` is a silent no-op | `:189-190` | — | M |
| Concurrent runners | `select_for_update` at `:197` | — | BU |
| Beat and cron both running (double fire) | none | — | M (owner) |
| Operators can see scheduler failures. `PeriodicTaskRun` is in no admin, API or metrics view, and `run.sh:48` and `cloud.yml:209` swallow errors with `\|\| true` | — | — | M (owner) |

## 10. Live updates (SSE)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Anonymous refused; channels scoped by RBAC | `views_live.py:32-41,80` | Two tests in `tests/test_live_stream.py` | BT |
| No Redis → 503, and publishing is a no-op | `views_live.py:97-99`; `live.py:82-83` | Two tests | BT |
| Redis present → events stream, with the retry header and X-Accel-Buffering | `views_live.py:44-56,107-113` | `::test_stream_emits_events_from_the_subscribed_channels` | BT |
| Events published only after commit, with no PII | `live.py:85-93` | Two tests | BT |
| Redis down at subscribe time → 503 | `views_live.py:101-106` | — | BU |
| Misconfigured `LIVE_REDIS_URL` → 500 | `live.py:51` runs outside the view's `try` | — | **BUG** |
| Redis outage mid-stream: an exception cuts the stream | `views_live.py:48` | — | **BUG** |
| The pubsub connection is never closed | `views_live.py:44-56` | — | **BUG** |
| Fallback to `CELERY_BROKER_URL` | `live.py:36` | — | BU |
| Re-authorisation mid-stream (a stream can live up to `LIVE_MAX_STREAM_SECONDS`=3600) | none | — | M (owner) |
| Rate limit or concurrent-stream cap | `throttle_classes=[]` | — | M (owner) |
| Caddy routes `/api/v1/live/` to `backend:8000` (sync, 60 s timeout) rather than the `live` service | `deploy/Caddyfile:4-5`; `Caddyfile.saas:15-16` | — | owner |
| The client stops on 401 or 503 and backs off after a dropped stream | `frontend/src/lib/live.ts:122-145` | `frontend/src/lib/live.test.ts` | BT |

## 11. Platform integration settings

### 11a. Email (platform SMTP and per-makerspace SMTP)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Platform SMTP configured or unconfigured; SSL vs STARTTLS | `apps/integrations/email.py:11-62` | Four tests in `tests/test_email_connection.py` | BT |
| `email_enabled()` matrix | `email.py:76-89` | Seven tests in `tests/test_email_enabled.py` | BT |
| A private or bad host is rejected on save; DNS rebinding is re-checked at delivery | `smtp_validation.py:43-80`; `email.py:17,48` | Six tests in `tests/test_smtp_validation.py` | BT |
| Undecryptable SMTP password | `makerspaces/secrets.py:15-22` → `dispatch.py:231-233` | — | BU |
| `platform_email_configured()` checks only the host, so an unreadable password still counts as configured | `email.py:65-69` | — | gap |
| SMTP outage; async forced failure | `dispatch.py:231-250` | `tests/test_email_log.py::test_dispatch_email_failure_logs_error_without_raising`, `tests/test_email_async.py::test_async_dispatch_records_forced_send_failure` | BT |
| SMTP timeout; staff notified on first failure; enqueue failure | `email.py:28,59`; `dispatch.py:174-190,241-250` | — | BU |
| `email` module off → mail skipped and recorded | `dispatch.py:33-45,81-97,205-209` | All of `tests/test_email_module_gating.py` | BT |
| `email` module off → settings, templates and logs routes | No route gate; they still answer 200 | — | owner |
| Managed daily cap / self-host uncapped / platform mail uncapped | `dispatch.py:99-143` | Three tests in `tests/test_managed_limits_enforcement.py` | BT, except §0.2 |
| Actors: superadmin 200, regular user 403 | `views_platform.py:55-61` | `tests/test_password_reset_self_service.py::test_platform_email_settings_superadmin_only_and_write_only_password` | BT |
| Actors: Space Manager, anonymous, API client | Same | — | BU |
| A test-send endpoint | none | — | M (owner) |

### 11b. SMS (`PlatformSmsSettings`, Twilio) and phone login

| Condition | Code | Tests | Status |
|---|---|---|---|
| Unconfigured or switch off → hidden, 404 | `integrations/sms/__init__.py:88-107`; `accounts/views_phone.py:81-88` | Three tests in `tests/accounts/test_phone_auth_p8.py` | BT |
| Configured | Same | `::test_phone_login_appears_in_config_once_configured` (the fixture mocks `send_sms`) | BT; Twilio itself never runs |
| Partial credentials; unknown provider; undecryptable token; Twilio 4xx or 5xx; timeout; the provider raising | `sms/twilio.py:174-231`; `sms/__init__.py:101-125` | — | BU |
| Phone switch off; member ecosystem off | `views_phone.py:43-56` | `tests/accounts/test_login_methods_p10.py::test_phone_sign_in_is_refused_when_off`; `tests/modules/test_offstate_identity.py::test_member_accounts_off_refuses_phone_login_but_keeps_walk_ins_and_oidc` | BT |
| `OTP_SMS_DAILY_CAP` | `makerspaces/limits_reservations.py:64-103` | — | BU |
| Rate limits (429); resend cooldown | `accounts/throttles.py:39-95`; `services_phone.py:81-86` | — | BU |
| Separate request and guess budgets, attempt cap, single use, no enumeration, suspension | `services_phone.py` | Nine tests | BT |
| Not-configured answers 404, not 400 | `views_phone.py:4-6` (documented contract) | — | owner |

### 11c. Native push (`PlatformPushSettings`, FCM, APNs)

| Condition | Code | Tests | Status |
|---|---|---|---|
| Unconfigured → inert; off by default for every feature | `push.py:91-111` | `tests/test_native_push.py::test_missing_platform_credentials_are_inert`, `::test_native_push_defaults_off_for_every_feature` | BT |
| `mobile.push` switch off | `push.py:105-108` | `tests/test_a6_toggle_scoping.py::test_push_switch_gates_delivery_without_replacing_the_credential_check` | BT, but the row is labelled `notification_channel_not_configured` |
| Invalid device token deactivated | `push.py:139-143` | `::test_invalid_provider_token_is_deactivated_without_leaking_token` | BT |
| Undecryptable credentials; malformed service account; bad private key (misclassified as transient); FCM/APNs 4xx/5xx and timeouts | `push_fcm.py:214-254`; `push_apns.py:166-199` | — | BU |
| No devices, or the device platform is unconfigured → the row says SENT | `push.py:131-136,157` | — | gap: false SENT |
| Registration: idempotent, attested identity, owner-only delete | `views_push.py:29-112` | Three tests | BT |
| Missing `PUSH_TOKEN_HMAC_KEY` → 503; owner conflict → 409; registration rate limit | `views_push.py:21-60` | — | BU |

### 11d. Stripe Connect and the payment rail

| Condition | Code | Tests | Status |
|---|---|---|---|
| Platform Connect settings: write-only for the superadmin; others 403; rotation blocked while a session is pending | `views_platform_payments.py:16-32`; `payments/credential_validation.py` | `tests/payments/test_payment_settings.py`, `tests/payments/test_platform_payment_settings_validation.py` | BT |
| Self-host: platform settings and onboarding → 404 | `views_platform_payments.py:22-23`; `views_payment_settings.py:97-100` | — | BU |
| Self-host: callback and webhook → 404 | `views_connect.py:116-117,276-279` | `tests/payments/test_connect_corrective.py::test_connect_callback_is_not_available_in_self_host_mode`; `tests/payments/test_webhook_decryption_fail_safe.py::test_self_host_connect_webhook_returns_404_before_decryption` | BT |
| Onboarding unconfigured → 503 | `connect.py:51` | — | BU |
| Rail tombstoned | `config/urls.py:88-140` | `tests/tombstone/test_payments_removed_surfaces.py` (Razorpay webhook and connect/onboard not parametrised) | T(local) |
| Webhook: missing key or corrupt ciphertext → sanitised 400 | `views_connect.py:287-292`; `payments/views.py:40-50` | Three tests in `test_webhook_decryption_fail_safe.py` | BT |
| Raw Stripe: invalid signature; real HMAC end to end | `views.py:40-50` | `tests/payments/test_models.py::test_webhook_rejects_invalid_signature`; `tests/payments/test_archived_space_payments.py::test_raw_stripe_webhook_settles_after_archival` | BT |
| Connect webhook: bad signature with a valid secret; empty secret | `views_connect.py:293-298`; `stripe_client.py:169-170` | — | BU |
| Replay and idempotency | — | Four tests across `tests/payments/` | BT |
| Razorpay: forged, missing or exact-bytes signature; wrong provider; replay; archived space | `views.py:57-121` | Six tests | BT |
| Razorpay: a non-ASCII signature header → `TypeError` → 500 | `razorpay.py:167` | — | **BUG** (§0.3) |
| OAuth state replay; stale callback; replacement | `views_connect.py:115-257` | Several tests | BT |
| `payments` module off → member checkout answers 503, not 400; payment-settings routes ungated | `payments/availability.py:21-26` | — | owner |

### 11e. OIDC, social sign-in and the four login-method switches

| Condition | Code | Tests | Status |
|---|---|---|---|
| Unconfigured → hidden, 404; a disabled, half-filled or unknown OIDC provider does not resolve | `social_nonces.py:54-80`; `models_oidc.py:75-93` | Five tests | BT |
| Google token: signature, iss, aud and nonce checked; OIDC `email_verified` must be literally true | `social_jwt.py:147-174`; `social_oidc.py:27` | Two tests | BT |
| Apple token, including the hashed-nonce branch | `social_apple.py:8-34` | — | BU |
| JWKS outage, timeout, non-200, oversize, malformed, or more than 16 keys → 503; key-rotation refresh | `social_jwt.py:155-216` | — | BU |
| Discovery: issuer mismatch, redirect, size, slowness; token endpoint 4xx | `oidc_browser_http.py:20-103` | Two tests | BT |
| Token endpoint 5xx or malformed response | Same | — | BU |
| Nonce and state replay | `social_nonces.py:130-194`; `oidc_browser_attempts.py` | Four tests | BT |
| Password, social and self-registration switches off; /control/ lockout guards; switch reads fail open | `login_methods.py`; `admin_social.py:89-125` | Ten or more tests across `tests/accounts/` | BT |
| Per-provider lockout guard in the **API** | `views_platform_social.py:41-48` | — | **M** (§0.13) |
| Disabling an OIDC provider has no lockout guard (only delete is blocked) | `admin_social.py:166-188` | — | owner |
| An OIDC identity can be linked but not unlinked | `views_social.py:273-274` (a provider not in `SocialProvider.values` gets 404) | — | M |
| The nonce endpoint ignores the social switch | `views_social.py:80-89` | — | gap |

### 11f. Secrets

- **Encrypted at rest.** Every credential is Fernet-encrypted through
  `makerspaces/secrets.py:6-22` / `apiclients/crypto.py`. This covers the email, SMS, push,
  per-makerspace, payment and social models.
- **Write-only.** Serializers and `/control/` forms never return the stored value. Pinned by
  `tests/test_password_reset_self_service.py::test_platform_email_settings_superadmin_only_and_write_only_password`,
  `tests/payments/test_payment_settings.py::test_platform_connect_admin_form_is_write_only_and_global`
  and `tests/accounts/test_social_auth.py::test_platform_settings_api_keeps_apple_key_write_only`.
- **Never logged.** Logs carry only the exception class or HTTP status, never a body or a
  credential.
- **Never exported.**
  - Whole platform-credential models are omitted: `data_export/classification_platform.py:46-127`.
  - Per-field secrets are always omitted: `data_export/fields.py:82-93`.
  - Guard regex: `data_export/guards.py:34`.
- **Caveats.** `decrypt_value` passes legacy plaintext through unchanged. There is no
  MultiFernet and no re-encryption command. Nothing checks at boot that `API_CLIENT_ENC_KEY`
  is set.

### 11g. `/control/` edits that write no `audit.record`

These edits are recorded only in Django's `LogEntry`:

- `integrations/admin.py:28-35` (PlatformEmailSettings)
- `admin_sms.py:38-46`
- `admin_push.py:25-37`
- `admin_social.py:64-73,128-148,166-188`
- `payments/admin.py:114-117` (MakerspacePaymentSettings)
- `apps/updates/admin.py:9-35`

## 12. Outbound channels

### 12a. Send paths and the fail-safe contract

| Channel | Path | Never raises into the caller | Retry classification | Status |
|---|---|---|---|---|
| Email | `dispatch.py:58-266`, `tasks.py:286-311` | Yes, except §0.2 | FAILED → `self.retry` | BT, except **BUG** §0.2 |
| Telegram | `telegram.py:41-81` → `dispatch_channels.py:225-295` | Yes | `notification_delivery_failed:*` | BT with the transport mocked only |
| Slack, Mattermost, Discord | `webhooks.py:172-220` | Yes | Same | BT with the transport mocked only |
| Signed webhook | `webhooks.py:252-277` | Yes | Same | BT with the transport mocked only |
| Native push | `push.py` | Yes | Same | §11c |

### 12b. Provider-failure matrix, before this lane

| Condition | Telegram | Slack, Mattermost, Discord | Signed webhook | SMTP |
|---|---|---|---|---|
| 2xx → SENT | `test_telegram_integration.py::test_telegram_delivery_uses_decrypted_makerspace_bot_token` | — | `test_webhook_channel.py::test_delivery_posts_signed_json_and_marks_sent` | `test_email_log.py` |
| Unconfigured → terminal FAILED | `::test_test_alert_unconfigured_returns_delivered_false_with_detail` | — | `::test_without_a_secret_or_destination_the_channel_is_not_configured` | `test_email_enabled.py` |
| Timeout, refused connection or malformed response | — | — | — | `test_email_async.py` |
| HTTP 4xx, 429 or 5xx | — | — | — | n/a |
| Redirect loop | — | — | SSRF redirect only | n/a |
| Transport mocked wholesale → FAILED, URL kept out of the error | `::test_test_alert_delivery_failure_returns_delivered_false_not_500` | — | `::test_failed_delivery_is_recorded_not_raised` | — |
| Module off → SKIPPED | `test_notification_channel_modules_p10.py` | Same | `::test_module_off_skips_instead_of_sending` | `test_email_module_gating.py` |
| Bot token kept out of logs | — | n/a | n/a | n/a |

Every "—" cell in the timeout, 4xx/429/5xx and redirect rows is **BU**. The code classifies
these failures correctly (`webhooks.py:188-191`, `telegram.py:68-80`), but no test drives a
real HTTP status or socket error through `_deliver` / `urlopen` for any chat channel.

### 12c. Delivery logs, retries, re-queue, mutes and health

| Condition | Code | Tests | Status |
|---|---|---|---|
| Email retry service: only FAILED or stale SENDING rows, audited | `apps/integrations/services.py:13-40` | `tests/test_admin_parity_actions.py::test_email_retry_action_routes_through_service_and_rejects_non_failed` | BT |
| Re-queueing a notification from `/control/` | `admin_notifications.py:42-61` | — | **BU** |
| Re-queue while the broker is down | `dispatch_channels.py:208-222` | — | BU |
| Only `notification_delivery_failed:*` rows are retried | `tasks.py:355-363` | `tests/test_notification_dispatch.py` | BT |
| Health: email counts, stalled sends, last failure, worker heartbeat, a failing section fails safe | `health.py:25-231` | Six tests in `tests/test_integration_health.py` | BT |
| Health: per-destination failed count and last failure | `health.py:106-180` | Backend tested | BT in the backend; **the console never renders it** |
| Health: failures of legacy (destination-less) chat deliveries | none | — | M |
| Telegram webhook: secret unset or wrong → 403; callback ignored; throttled | `views.py:57-67,121-130` | Four tests | BT |
| Telegram webhook: a non-ASCII secret header → 500 | `views.py:130` | — | **BUG** |
| Outbound webhook signature `t=..,v1=hmac(t.body)`; SSRF pinning | `webhooks.py:229-235`; `webhook_validation.py` | `test_webhook_channel.py::test_signature_is_hmac_over_timestamp_dot_body`; four tests in `test_webhook_ssrf.py` | BT |

## 13. API clients and the protected-route registry

| Condition | Code | Tests | Status |
|---|---|---|---|
| Issue: the raw secret is shown once, encrypted at rest, and needs at least one exact origin | `apiclients/models.py:83-110` | `tests/test_apiclients.py::test_issue_returns_raw_secret_and_stores_it_encrypted`; five tests in `tests/test_apiclient_validation.py` | BT |
| Valid signature; unknown client; disallowed origin; inactive client | `apps/inventory/middleware.py:87-185` | Four tests in `tests/test_apiclients.py` | BT |
| A bad signature is refused and does not consume the nonce | `middleware.py:165-169` | `tests/test_apiclient_secret_rotation.py::test_bad_signature_does_not_consume_nonce` | BT |
| Timestamp outside the skew window, in the future, or not an integer | `middleware.py:116-123` | — | **BU** |
| Nonce replay (Redis and DB caches); tampering; per-client namespace; malformed nonce; nonce required | `middleware_nonce.py:33-39` | Seven tests in `tests/test_apiclient_nonce.py` | BT |
| A body that could be read as a nonce is refused | `middleware.py:131-136` | Three tests | BT |
| Nonce cache outage → fails closed (401, not 500) | `middleware.py:180-184` | — | **BU** |
| Undecryptable stored secret (`API_CLIENT_ENC_KEY` changed) → 401 | Same | — | **BU** |
| Secret rotation | `api_client_views.py` | Seven tests | BT |
| Scope registry; unknown-route denial; `legacy:v1`; system check | `scope_registry*.py`, `checks.py` | 30 tests | BT |
| Rate tiers | `throttling.py` | Five tests | BT |
| Enforcement staging; usage telemetry with Redis down | `middleware_observability.py`; `telemetry.py` | 15 tests | BT |
| Key requests: creation audited, membership-gated, `/control/` approval validates | `admin_api/api_key_request_views.py:35-61` | `tests/test_apiclient_validation.py::test_control_approve_surfaces_validation_error_without_creating_client` | BT |
| Key requests with `?makerspace=abc` → 500 | `api_key_request_views.py:30-32` | — | **BUG** |

## 14. Object storage

| Condition | Code | Tests | Status |
|---|---|---|---|
| Presigning targets the staging key; a replay cannot replace the final object; promotion happens once | `apps/evidence/storage.py:100-140` | Two tests in `tests/test_put_finalize.py` | BT |
| PUT mode; quota charged once; public-image retry and size check | `STORAGE_PRESIGN_METHOD` | Four tests in `tests/test_put_finalize.py` | BT |
| S3 outage → `StorageUnavailable` → 503 on evidence presign, finalize and read | `apps/evidence/storage.py:62-210`; `apps/evidence/views.py:75,176,188` | `tests/test_evidence.py`, `tests/test_issue.py`, `tests/test_return_validation.py` | BT |
| Versioned delete fallback; access denied; paging failure | `apps/object_storage.py:21-109` | Five tests in `tests/test_object_storage.py` | BT |
| Equal bucket names refused | `config/storage_validation.py` | Two tests | BT |
| Managed storage counter and `recompute_storage` | `limits.add_storage/free_storage` | `tests/test_managed_limits_enforcement.py::test_managed_storage_add_free_boundary_and_clamp_without_outer_atomic`; `tests/test_storage_reconciler_gaps.py` | BT |

## 15. OpenAPI completeness

Measured with `manage.py spectacular` at `b7c2ee93`: 612 operations, of which **151 document
no 4xx/5xx response**.

The committed snapshot already differs from a fresh generation by one
`"default": "pending"` at `frontend/openapi-schema.json:53748`. That drift predates this lane.

In-scope operations with no error responses (expected codes in brackets):

- `/api/v1/health/` and `/health/readiness/` — GET [readiness can answer 503]
- `/api/v1/integrations/telegram/webhook` — POST [403, 400, 429]
- `/api/v1/integrations/telegram/test-alert` — POST [400 module off, 403, 404]
- `/api/v1/admin/platform/email-settings` — GET, PATCH
- `/api/v1/admin/platform/social-auth-settings` — GET, PATCH
- `/api/v1/admin/platform/payment-settings` — GET, PATCH
- `/api/v1/admin/platform/update-settings` — GET, PATCH; `/update-now` — POST
- `/api/v1/admin/api-key-requests` — GET, POST
- `/api/v1/admin/makerspace/{id}/api-settings` — GET, PATCH
- `/api/v1/admin/makerspace/{id}/notification-destinations` — GET; `/{destination_id}` — DELETE
- `/notification-recipient-rules` — GET
- `/notification-recipients` — GET, PATCH
- `/notification-rules` — GET
- `/email-templates` and its preview, detail and reset routes
- `/modules` — GET
- `/api/v1/auth/social/providers` — GET
- `/api/v1/auth/phone` — DELETE
- `/api/v1/config` — GET

Responses that exist but lack a description, or codes that are missing:

- `/api/v1/metrics/`: 401 and 404 are declared as `None`.
- `/api/v1/live/`: 401 and 403 are missing.
- `/api/v1/internal/tls-check`: the 400 from the host gate and the 503 from the recovery gate
  are missing.
- Social nonce, login and link: 403, 503 and 404 are missing.
- OIDC start and callback: 429 is missing.
- The `Internal` and `Admin hosting` tags are not declared.

## 16. Environment-surface completeness

`ENV_SURFACE` in `apps/backup/settings_policy.py` holds **247** names. I compared it against
the three env examples (`.env.example`, `.env.production.example`, `backend/.env.example`)
and against every `docs/*.md` file plus `README.md`.

| Measure | Count | Verdict |
|---|---|---|
| In no example and no doc | 112 | — |
| In no env example | 143 | Mostly correct: the drift test's own docstring argues that tuning knobs whose defaults are right off-box do not belong in an example |
| In no doc | 167 | Not correct: an operator has nowhere to look these up |

Other env-surface gaps:

- `docker-compose.cloud.yml` and the `docker/compose.{saas,tls,single}.yml` overlays are not
  in `PRODUCTION_MANIFESTS`.
- No compose file passes `METRICS_TOKEN` or `SENTRY_*` (§0.7).

## 17. Console parity

| Surface | Shows "not configured" | Shows "last delivery or check failed" | Evidence |
|---|---|---|---|
| Email (makerspace) | Yes | Yes | `IntegrationHealthPanel.tsx:82-114` |
| Telegram (legacy columns) | Yes | No | `:116-118` |
| Chat and webhook destinations | Backend yes | Backend yes, **console no** | `health.py:106-180` |
| Legacy-column Slack, Mattermost and Discord failures | Backend boolean only | Nowhere | `health.py:173-180` |
| Worker | Yes | Yes (stale) | `:120-130` |
| Software updates | "Host has not checked in" only | "Update failed" plus `last_error`. A rollback looks the same; a stale RUNNING locks the panel; module off shows the raw 404 | `PlatformUpdatePanel.tsx:25-146` |
| Platform email, social and Stripe Connect panels | Only "secret set" placeholders | No | `PlatformEmailPanel.tsx:84`, `PlatformStripeConnectPanel.tsx:78-80`, `PlatformSocialAuthPanel.tsx:87` |
| SMS, push, login methods, OIDC | No staff-console panel | — | — |
| `/control/` sidebar | Only platform email and Stripe Connect are listed. SMS, push, login methods, social and OIDC are registered but have no entry | — | `config/unfold.py:180,183` |
| `/control/` `PeriodicTaskRun` | Not registered | No | — |
| Email log panel | It has no `skipped` status filter | — | `EmailLogPanel.tsx:7` |

## 18. Items needing an owner decision

1. **SaaS client IP behind Cloudflare.** Should throttles take the client IP from Caddy
   `trusted_proxies` plus `CF-Connecting-IP`, or from `TRUSTED_PROXY_COUNT=2`?
2. **The cron endpoint.** Should it be public (as `docs/deploy-production.md` says) or
   internal-only? Should cron runs be throttled or audited?
3. **HSTS defaults.** `ENABLE_HTTPS` switches on `includeSubDomains` and `preload`
   automatically, including on tenant custom domains. Preload is hard to undo.
4. **Cache outage on the managed host allowlist.** It currently fails closed, so every custom
   domain answers 400 while Redis is down.
5. **Liveness and readiness.** Liveness returns 503 when the DB is down. Readiness exposes
   custody counts to anonymous callers.
6. **Rate limits.** Verify-domain, subdomain requests and the live stream have none. The live
   stream also has no re-authorisation interval.
7. **Headers.** SPA security headers in nginx; `X-Request-ID` in the CORS expose headers;
   tagging Sentry events with the request ID.
8. **Updates.**
   - Whether the host updater should honour the module switch.
   - How long Update now may wait, given the weekly cron.
   - Whether to add real `rolled_back` and `check_failed` statuses.
   - Downgrade protection.
   - Verifying images before a release is marked latest.
9. **Scheduler.** Guarding against beat and cron double-firing; whether at-most-once is
   acceptable; surfacing `PeriodicTaskRun`.
10. **Caddy routing for `/api/v1/live/`.**
11. **`BEHIND_TRUSTED_PROXY` and managed mode.** On self-host it disables host validation.
    Should managed mode refuse to start without it?
12. **CI for the tombstone suite**, run once per profile.
13. **Module-off answers.**
    - Should module-off settings, template and log routes for `email` and `payments` answer
      400? Today only dispatch is gated.
    - Phone, social and Connect on self-host answer 404 by documented contract.
14. **Gating.** Should push registration and phone or social linking honour the platform
    switches? Should disabling an OIDC provider get a lockout guard?
15. **Rotating `API_CLIENT_ENC_KEY`.** Should rotation be supported (MultiFernet or a
    re-encrypt command), and should the server refuse to start in production when the key is
    empty?
16. **Sign in with Apple** client-secret generation and token revocation. This needs an Apple
    Developer account.
17. **Test-send endpoints** and a persisted "last delivery failed" state for SMTP, SMS,
    FCM/APNs and Stripe. Real validation needs paid or sandbox provider accounts.
