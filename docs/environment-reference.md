# Environment reference

Every environment variable the backend reads, grouped by area. The complete list spans
this page, [delivery, sign-in and rate limits](environment-reference-delivery.md),
and [operations](environment-operations.md):
`backend/tests/test_environment_reference_drift.py` fails when a name in
`apps/backup/settings_policy.ENV_SURFACE` (itself pinned to what the code reads) is missing
here. The env examples (`.env.example`, `.env.production.example`, `backend/.env.example`)
deliberately carry only what a deployment must decide; everything else has a default that
is correct off-box, shown below. Installer/Compose-only rows are classified separately
in `apps/backup/settings_policy.HOST_ONLY_POLICIES`: they are excluded from backend
restore compatibility and checked through the host topology record instead.

Defaults are the expressions in `backend/config/settings.py`; "read outside `settings.py`"
means a command, script or app module reads it directly (setup, build, host orchestration).

WP3 quiet hours, digest times and bounce signing credentials are tenant settings,
not environment variables. Booking ICS uses the existing
`THROTTLE_EVENT_CALENDAR_FEED_TOKEN` (120/hour) and `THROTTLE_EVENT_CALENDAR_FEED_IP`
(300/hour) budgets with separate booking cache keys; see the delivery reference.

## Core Django and hosting

Read by every backend process. `ALLOWED_HOSTS`, `SECRET_KEY` and the proxy posture must be set for any off-box deployment.

| Variable | Default | Notes |
|---|---|---|
| `ADMIN_SITE_NAME` | `'Space Works'` |  |
| `ALLOWED_HOSTS` | `['localhost', '127.0.0.1']` | Django's host check; add every custom domain on self-host. |
| `CORS_ALLOWED_ORIGINS` | `['http://localhost:5000', 'http://localhost:5173']` |  |
| `CSRF_TRUSTED_ORIGINS` | `[]` |  |
| `DEBUG` | — | Must be false off-box; it also selects JSON logs and several defaults. |
| `INFRA_HOSTS` | `['localhost', '127.0.0.1', 'backend', 'backend:8000']` | Container hostnames recognised as infrastructure callers by the managed host gate. |
| `LOG_JSON` | `not DEBUG` |  |
| `LOG_LEVEL` | `'INFO'` |  |
| `PUBLIC_APP_BASE_URL` | `''` | Browser origin used in emailed links. Blank falls back to localhost, which is unclickable for real users. Personal optional mail emits RFC 8058 one-click headers only with an HTTPS origin whose `/api/v1` path reaches the backend. |
| `SECRET_KEY` | — | Required. Rotating it invalidates sessions and signed tokens. |
| `SPACEWORKS_EDITION` | `'makerspace'` |  |
| `TOMBSTONED_APPS` | read outside `settings.py` | Comma-separated separable apps to remove from this deployment. |

## Production release deployment

Automatic deploys use an optional Linux/systemd GitHub Actions runner. Register it with
`bash scripts/install-runner.sh`; set the GitHub repository variable `SPACEWORKS_DEPLOY=true` only after
applying the [required security settings](self-hosting.md#security). This variable belongs in GitHub,
not the application `.env`. The runner `.env` contains `SPACEWORKS_DIR` for the installed updater.
`SPACEWORKS_RUNNER_DIR` optionally selects its directory (default `/opt/spaceworks-runner`) when invoking
the helper. Manual updates use `bash scripts/update.sh --force`, optionally with `--version` for an exact
published main release. Forks configure their own repository, releases, runner and deploy variable.

| Variable | Default | Notes |
| --- | --- | --- |
| `SPACEWORKS_REPOSITORY` | `SpaceWorks-HQ/SpaceWorks` | Strict GitHub `owner/repo`; installer source, release lookup and runner registration URL. Persisted in `.env`. The lower-cased owner supplies default GHCR backend/frontend image namespaces unless `MAKERSPACE_BACKEND_IMAGE` / `MAKERSPACE_FRONTEND_IMAGE` override them. |

## TLS, cookies and proxies

TLS hardening is gated on `ENABLE_HTTPS`, never on `DEBUG`. Internal plain-HTTP probes (`/api/v1/health/`, `/api/v1/internal/`, `/api/v1/metrics/`) are exempt from the HTTPS redirect (`SECURE_REDIRECT_EXEMPT`).

| Variable | Default | Notes |
|---|---|---|
| `AUTH_COOKIE_SAMESITE` | `'None'` |  |
| `AUTH_COOKIE_SECURE` | `True` |  |
| `AXES_ENABLED` | `True` |  |
| `AXES_FAILURE_LIMIT` | `5` |  |
| `BEHIND_TRUSTED_PROXY` | `False` | Lets the managed host middleware be the host boundary (`ALLOWED_HOSTS=['*']`). |
| `CSRF_COOKIE_SECURE` | `ENABLE_HTTPS` |  |
| `ENABLE_HTTPS` | `False` | Turns on the HTTPS redirect, Secure cookies and HSTS (1 year, includeSubDomains, preload). |
| `SECURE_HSTS_SECONDS` | `31536000 if ENABLE_HTTPS else 0` | Start at 0 or small while verifying domains. |
| `SECURE_SSL_REDIRECT` | `ENABLE_HTTPS` |  |
| `SESSION_COOKIE_SECURE` | `ENABLE_HTTPS` |  |
| `TRUSTED_PROXY_COUNT` | `None` | Proxies in front of the backend; required when DEBUG is off. Throttles key on the real client IP only when this is right. |
| `TRUST_X_FORWARDED_PROTO` | `False` | Trust the proxy's `X-Forwarded-Proto`; only behind a TLS proxy that is the sole path in. |

## Managed SaaS mode

Every managed feature is dormant while `PLATFORM_DOMAIN_SUFFIX` is blank (self-host). See `docs/deploy-saas.md`.

| Variable | Default | Notes |
|---|---|---|
| `DOMAIN_CHANGE_COOLDOWN_SECONDS` | `0` | Managed mode: wait between custom-domain changes. |
| `PLATFORM_ADMIN_SSO` | `False` |  |
| `PLATFORM_DOMAIN_SUFFIX` | `''` | Blank = self-host. Non-blank activates managed mode and fair-use limits. |
| `PLATFORM_ORIGIN_HOST` | `''` |  |
| `PLATFORM_STAFF_ORIGINS` | `[]` |  |
| `PLATFORM_SUBDOMAIN_AUTO_TLS` | `False` | Guided platforms enable TLS admission for registered, verified, non-archived tenant subdomains. Unknown/pending/archived domains remain denied. Compared during restore preflight without blocking a target's TLS choice. |

## Database

| Variable | Default | Notes |
|---|---|---|
| `CONN_HEALTH_CHECKS` | `True` |  |
| `CONN_MAX_AGE` | `60` | Set 0 on a transaction pooler (Supabase :6543). |
| `DATABASE_URL` | read outside `settings.py` | Supplied by the atomic ops pointer under Compose; never put it in a static `.env`. |
| `DISABLE_SERVER_SIDE_CURSORS` | `False` |  |
| `MANAGED_POSTGRES` | `False` | True on hosts that forbid `session_replication_role` (Supabase, RDS). |
| `SPACEWORKS_GRANTS_ONLY` | read outside `settings.py` |  |
| `SPACEWORKS_GRANT_DATABASE_NAME` | read outside `settings.py` |  |
| `SPACEWORKS_RUNTIME_DATABASE_URL` | read outside `settings.py` |  |

## Cache, Celery, scheduler and live updates

Redis backs the cache (rate limits, nonces, verified hosts), the Celery broker and the SSE stream. Without a broker, tasks run eagerly and the live stream answers 503.

| Variable | Default | Notes |
|---|---|---|
| `CACHE_URL` | `''` |  |
| `CELERY_BROKER_URL` | `''` |  |
| `CELERY_RESULT_BACKEND` | `''` |  |
| `CELERY_TASK_ALWAYS_EAGER` | `_celery_broker == ''` |  |
| `REMINDER_SWEEP_BATCH_SIZE` | `200` | Positive subject/claim batch per source and makerspace; shared reminders run every five minutes. Also bounds each inbox/delivery retention batch, including platform email logs (90 days read/sent/skipped, 365 failed; unread/in-flight kept). |
| `CRON_SECRET` | `''` | Enables `POST /api/v1/internal/cron/return-reminders`; 404 while unset. |
| `LIVE_MAX_STREAM_SECONDS` | `3600` |  |
| `LIVE_REDIS_URL` | `''` | Defaults to the Celery broker; empty or unparseable makes `/api/v1/live/` answer 503 and the console polls. |
| `SPACEWORKS_SCHEDULER_CONTROL_PLANE_DISABLEMENT` | read outside `settings.py` |  |
| `SPACEWORKS_SCHEDULER_HOST_GATE_COMMAND` | read outside `settings.py` |  |
| `SPACEWORKS_SCHEDULER_MODE` | read outside `settings.py` |  |
| `SPACEWORKS_SCHEDULER_SERVICES` | read outside `settings.py` |  |

## Observability

| Variable | Default | Notes |
|---|---|---|
| `METRICS_TOKEN` | `''` | Bearer token for `GET /api/v1/metrics/`; 404 while unset. |
| `SENTRY_DSN` | `''` | Opt-in error tracking; the SDK is imported only when set; PII is never sent. |
| `SENTRY_ENVIRONMENT` | `'production' if not DEBUG else 'development'` |  |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` |  |

## Object storage

`AWS_S3_ENDPOINT_URL` is what the backend talks to; `AWS_S3_PUBLIC_ENDPOINT_URL` is what browsers see inside presigned URLs.

| Variable | Default | Notes |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | `''` |  |
| `AWS_S3_ENDPOINT_URL` | `'http://localhost:9000'` |  |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | `AWS_S3_ENDPOINT_URL` | Must be browser-reachable; on-box default only works on the server itself. |
| `AWS_S3_REGION_NAME` | `'us-east-1'` |  |
| `AWS_SECRET_ACCESS_KEY` | `''` |  |
| `AWS_STORAGE_BUCKET_NAME` | `'evidence'` |  |
| `PUBLIC_IMAGE_BASE_URL` | `''` | Public base URL of `PUBLIC_IMAGE_BUCKET`. |
| `PUBLIC_IMAGE_BUCKET` | `'public-images'` |  |
| `PUBLIC_IMAGE_MAX_BYTES` | `10485760` |  |
| `PUBLIC_IMAGE_URL_TTL_SECONDS` | `300` |  |
| `STORAGE_PRESIGN_METHOD` | `'post'` | `post` (MinIO) or `put` (R2, Supabase Storage). |

## Upload limits and evidence retention

Personal subject exports reuse the tenant export limits and private bucket above;
this feature introduces no new environment variables. Signed links use the browser
storage endpoint and expire no later than the archive retention boundary.

| Variable | Default | Notes |
| --- | --- | --- |
| `DATA_EXPORT_DEADLINE_SECONDS` | `900` | Maximum worker build time for tenant and personal exports. |
| `DATA_EXPORT_PAGE_SIZE` | `500` | Database iterator batch size for export rows. |
| `DATA_EXPORT_RETENTION_SECONDS` | `604800` | Archive retention (seven days), including personal ZIPs. |
| `DATA_EXPORT_DOWNLOAD_TTL_SECONDS` | `300` | Maximum personal signed-link lifetime (five minutes). |

| Variable | Default | Notes |
|---|---|---|
| `EVIDENCE_ABANDONED_UPLOAD_CLEANUP_ENABLED` | `False` | Deployment switch for deleting upload slots no workflow consumed; each makerspace must also opt in. |
| `EVIDENCE_ABANDONED_UPLOAD_RETENTION_DAYS` | `7` | Default age before an unconsumed upload slot is eligible. |
| `EVIDENCE_MAX_BYTES` | `10485760` |  |
| `EVIDENCE_OBJECT_EXPIRY_ENABLED` | `False` |  |
| `EVIDENCE_OBJECT_RETENTION_DAYS` | `365` |  |
| `EVIDENCE_RETENTION_BATCH_SIZE` | `100` |  |
| `EVIDENCE_URL_TTL_SECONDS` | `300` |  |
| `MACHINE_DOC_ALLOWED_EXT` | `['pdf', 'jpg', 'jpeg', 'png', 'webp', 'stl', '3mf', 'step...` |  |
| `MACHINE_DOC_ALLOWED_MIME` | `['application/pdf', 'image/jpeg', 'image/png', 'image/web...` |  |
| `MACHINE_DOC_MAX_BYTES` | `10485760` |  |
| `PRINT_ALLOWED_MODEL_EXT` | `['stl', '3mf', 'step', 'stp', 'obj', 'amf', 'ply', 'gcode...` |  |
| `PRINT_ALLOWED_MODEL_MIME` | `['application/octet-stream', 'model/stl', 'application/sl...` |  |
| `PRINT_UPLOAD_MAX_BYTES` | `104857600` |  |
| `PRINT_URL_TTL_SECONDS` | `300` |  |
| `PROCUREMENT_RECEIPT_ALLOWED_MIME` | `['application/pdf', 'image/jpeg', 'image/png', 'image/webp']` |  |
| `PROCUREMENT_RECEIPT_MAX_BYTES` | `10485760` |  |
| `REPORT_DELIVERY_URL_TTL_SECONDS` | `6 * 60 * 60` |  |
| `WARRANTY_DOC_ALLOWED_MIME` | `['application/pdf', 'image/jpeg', 'image/png', 'image/webp']` |  |
| `WARRANTY_DOC_MAX_BYTES` | `10485760` |  |

## API clients (HMAC)

See `docs/api-client-protocol.md`.

| Variable | Default | Notes |
|---|---|---|
| `APICLIENT_REQUIRE_NONCE` | `False` | Refuse signed requests without `X-Nonce`. |
| `API_CLIENT_AUTH_REQUIRED` | `False` | Enforce client authentication on protected paths (otherwise log would-reject). |
| `API_CLIENT_ENC_KEY` | `''` | Fernet key for every stored integration secret. Back it up; changing it makes stored secrets unreadable. |
| `HMAC_CLIENT_ID` | `''` |  |
| `HMAC_MAX_CLOCK_SKEW_SECONDS` | `300` |  |
| `HMAC_PROTECTED_PATH_PREFIXES` | `['/api/public/', '/api/v1/public/']` | Paths that require a signed or publishable-key client. |
| `HMAC_SECRET` | `''` |  |
| `THROTTLE_CLIENT_PUBLIC` | `'30/min'` |  |
| `THROTTLE_CLIENT_STANDARD` | `'120/min'` |  |
| `THROTTLE_CLIENT_TRUSTED` | `'600/min'` |  |

## Two-step sign-in

Superadmins must enroll TOTP; staff enrollment is required when a space enables
`security.staff_mfa_required`. Members can opt in at `/mfa`. Secrets use the
existing `API_CLIENT_ENC_KEY` encryption; recovery codes are hashed. No separate key is needed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MFA_CHALLENGE_TTL_SECONDS` | `300` | Lifetime of the opaque first-factor proof (60–600 seconds); no JWT exists until verification. |
| `MFA_MAX_ATTEMPTS` | `5` | Failed second-factor attempts per challenge before refusal (1–10). |

### Staff invitations

Staff invitation links use `PUBLIC_APP_BASE_URL` or the verified tenant frontend domain.
The email module may be off; staff still receive a copyable link. Links expire in seven
days by default, contain a fragment token, and are single use. Existing accounts must
supply their password and enrolled second factor; an invitation cannot reset passwords.


## Installer topology selectors

These values are written after the shared deployment questionnaire is confirmed. Keep `.env` private.
The wrapper selects and validates the corresponding compose layers for setup, updates, rollback and
restore; missing selectors preserve the existing bundled stack. These rows are host/Compose-only
and excluded from backend backup preflight; `PLATFORM_SUBDOMAIN_AUTO_TLS` is a Django setting
documented under managed SaaS mode above.

| Variable | Default / meaning |
| --- | --- |
| `SPACEWORKS_HOSTING_MODEL` | `1`: one makerspace; `2`: shared `/m/<slug>` spaces; `3`: subdomain platform. Records intent; does not enforce a tenant-count limit. |
| `SPACEWORKS_RUN_FRONTEND` | `yes`; `no` disables the website and selects the API nginx edge. |
| `SPACEWORKS_STORAGE` | `bundled`; `external` disables Silo/MinIO and bucket initialization. |
| `API_BIND` | API edge listener address, default `0.0.0.0`; existing proxies use `127.0.0.1`. Built-in HTTPS removes this listener and uses Caddy. |
| `API_PORT` | API edge listener port, default `80`; existing proxies use `8080`. |
| `HTTP_PORT_BIND` | Website listener address, default `0.0.0.0`; existing proxies use loopback with `HTTP_PORT=8080`. |
| `SPACEWORKS_WEB_UPSTREAM` | `frontend:80` or `api-edge:80`, selected automatically for Caddy. |
| `TLS_EMAIL` | Required certificate-contact email for guided automatic HTTPS. |
| `PLATFORM_DOMAIN` | Platform apex DNS name used by the installer SaaS Caddy configuration. |
| `PLATFORM_FIRST_HOST` | First tenant API/site hostname; explicitly certified so API-only hosting can use a separate frontend origin. |
| `CADDY_SAAS_CONFIG` | Defaults to existing `./deploy/Caddyfile.saas`; new guided platforms use `./deploy/Caddyfile.saas-install` for public ACME. Existing deployments keep their origin-certificate configuration. |
| `STORAGE_DOMAIN` | Bundled HTTPS storage hostname (`files.<server/platform-domain>`). Requires DNS; an existing proxy forwards to loopback Silo port 9000. |
| `STORAGE_CADDY_CONFIG` | Defaults to `/etc/caddy/storage-disabled.caddy`; guided bundled HTTPS storage selects `/etc/caddy/storage.caddy`. External storage has no local route. |

External storage also writes existing `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_S3_ENDPOINT_URL`, `AWS_S3_PUBLIC_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_STORAGE_BUCKET_NAME`,
`PUBLIC_IMAGE_BUCKET`, `PUBLIC_IMAGE_BASE_URL` and `STORAGE_PRESIGN_METHOD` (`put` or `post`). The private
and public buckets must differ. The endpoint must be browser reachable; HTTPS sites need HTTPS endpoint
and image URLs. Configure provider CORS, private evidence policies, public-image reads and versioning
in the provider dashboard. Production Compose retains the bundled MINIO credential fallback.

API-only answers populate `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` and `PUBLIC_APP_BASE_URL` from
the supplied HTTPS origins; the first is the canonical staff website and makerspace `frontend_domain`.
Shared multi-tenant staff sites also populate `PLATFORM_STAFF_ORIGINS`. Set external frontend
`VITE_API_URL=https://<API-domain>/api`. The installer writes `ENABLE_HTTPS`,
`TRUST_X_FORWARDED_PROTO`, `TRUSTED_PROXY_COUNT`, `PLATFORM_DOMAIN_SUFFIX`, `BEHIND_TRUSTED_PROXY`,
`PLATFORM_ORIGIN_HOST` and `INFRA_HOSTS` to match the selected edge/proxy topology.
