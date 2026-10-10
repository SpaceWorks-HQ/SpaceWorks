# Environment reference

Every environment variable the backend reads, grouped by area. The complete list spans
this page and [delivery, sign-in and rate limits](environment-reference-delivery.md):
`backend/tests/test_environment_reference_drift.py` fails when a name in
`apps/backup/settings_policy.ENV_SURFACE` (itself pinned to what the code reads) is missing
here. The env examples (`.env.example`, `.env.production.example`, `backend/.env.example`)
deliberately carry only what a deployment must decide; everything else has a default that
is correct off-box, shown below.

Defaults are the expressions in `backend/config/settings.py`; "read outside `settings.py`"
means a command, script or app module reads it directly (setup, build, host orchestration).

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
| `PUBLIC_APP_BASE_URL` | `''` | Browser origin used in emailed links. Blank falls back to localhost, which is unclickable for real users. |
| `SECRET_KEY` | — | Required. Rotating it invalidates sessions and signed tokens. |
| `SPACEWORKS_EDITION` | `'makerspace'` |  |
| `TOMBSTONED_APPS` | read outside `settings.py` | Comma-separated separable apps to remove from this deployment. |

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
| `REMINDER_SWEEP_BATCH_SIZE` | `200` | Positive subject/claim batch per source and makerspace; shared reminders run every five minutes. |
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

## Scoped PII encryption

See `docs/scoped-pii-encryption.md`.

| Variable | Default | Notes |
|---|---|---|
| `PII_AWS_KMS_ENDPOINT_URL` | `''` |  |
| `PII_AWS_KMS_KEY_ID` | `''` |  |
| `PII_AWS_KMS_REGION` | `''` |  |
| `PII_DEK_CACHE_TTL_SECONDS` | `300` |  |
| `PII_ENCRYPTION_DUAL_READ` | `True` |  |
| `PII_ENCRYPTION_ENABLED` | `False` |  |
| `PII_KEY_BROKER` | `'local'` |  |
| `PII_MASTER_KEY` | `''` |  |
| `PII_MASTER_KEY_PREVIOUS` | `''` |  |
| `PII_SEARCH_HASH_KEY` | `''` |  |

## Audit attestation

| Variable | Default | Notes |
|---|---|---|
| `AUDIT_ATTESTATION_ANCHOR_BACKEND` | `''` |  |
| `AUDIT_ATTESTATION_DEPLOYMENT_ID` | `''` |  |
| `AUDIT_ATTESTATION_HTTP_BEARER_TOKEN` | `''` |  |
| `AUDIT_ATTESTATION_HTTP_TIMEOUT` | `10` |  |
| `AUDIT_ATTESTATION_HTTP_URL` | `''` |  |
| `AUDIT_ATTESTATION_RETENTION_DAYS` | `2555` |  |
| `AUDIT_ATTESTATION_S3_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` |  |
| `AUDIT_ATTESTATION_S3_BUCKET` | `''` |  |
| `AUDIT_ATTESTATION_S3_ENDPOINT_URL` | `AWS_S3_ENDPOINT_URL` |  |
| `AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE` | `'COMPLIANCE'` |  |
| `AUDIT_ATTESTATION_S3_PREFIX` | `'spaceworks-audit/v1'` |  |
| `AUDIT_ATTESTATION_S3_REGION_NAME` | `AWS_S3_REGION_NAME` |  |
| `AUDIT_ATTESTATION_S3_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` |  |
| `AUDIT_MAC_MASTER_KEY` | `''` |  |

## Backup, restore and tenant migration

Host-orchestration paths and timing knobs; see `docs/self-hosting.md` and the restore runbooks.

| Variable | Default | Notes |
|---|---|---|
| `BACKUP_AGE_RECIPIENT` | `''` |  |
| `BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY` | `''` |  |
| `BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY` | `''` |  |
| `BACKUP_DECISION_SECONDS` | `5 * 60` |  |
| `BACKUP_DOWNLOAD_TTL_SECONDS` | `5 * 60` |  |
| `BACKUP_LEASE_SECONDS` | `2 * 60 * 60` |  |
| `BACKUP_OPS_DIR` | `'/var/lib/spaceworks/ops'` |  |
| `BACKUP_PRESIGN_DRAIN_SECONDS` | `max(EVIDENCE_URL_TTL_SECONDS, PUBLIC_IMAGE_URL_TTL_SECOND...` |  |
| `BACKUP_PRODUCER_CAPABILITY_MARKER_PATH` | `'/run/spaceworks-host/producer-capability.json'` |  |
| `BACKUP_PRODUCER_ENTRYPOINT_PATH` | `'/app/scripts/spaceworks_entrypoint.py'` |  |
| `BACKUP_PRODUCER_MIGRATIONS_DIR` | `str(BASE_DIR / 'apps')` |  |
| `BACKUP_PRODUCER_PRIVILEGED_SCRIPTS_DIR` | `'/run/spaceworks-privileged-scripts'` |  |
| `BACKUP_RECIPIENT_CHALLENGE_TTL_SECONDS` | `15 * 60` |  |
| `DATA_EXPORT_DEADLINE_SECONDS` | `900` |  |
| `DATA_EXPORT_DOWNLOAD_TTL_SECONDS` | `5 * 60` |  |
| `DATA_EXPORT_PAGE_SIZE` | `500` |  |
| `DATA_EXPORT_RETENTION_SECONDS` | `7 * 24 * 60 * 60` |  |
| `SPACEWORKS_HOST_MARKER_PATH` | `'/run/spaceworks-host/restore-marker.json'` |  |
| `SPACEWORKS_HOST_MARKER_WRITE_PATH` | read outside `settings.py` |  |
| `SPACEWORKS_OCI_DIGEST` | read outside `settings.py` |  |
| `TENANT_DUMP_STAGING_DIR` | `''` |  |
| `TENANT_DUMP_STAGING_MAX_AGE_SECONDS` | `7 * 24 * 60 * 60` |  |
| `TENANT_MIGRATION_AGE_IDENTITY_FILE` | `''` |  |
| `TENANT_MIGRATION_AGE_RECIPIENT` | `''` |  |
| `TENANT_MIGRATION_GATE_LEASE_SECONDS` | `2 * 60 * 60` |  |
| `TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS` | `max(EVIDENCE_URL_TTL_SECONDS, PUBLIC_IMAGE_URL_TTL_SECOND...` |  |

## Connected devices

| Variable | Default | Notes |
|---|---|---|
| `DEVICE_COMMAND_LEASE_SECONDS` | `60` | Delivery lease for a printer/label command; covers delivery, not print duration. |
| `DEVICE_COMMAND_MAX_ATTEMPTS` | `10` | Bounded delivery retries before a command fails. |
| `DEVICE_ENROLLMENT_TTL_SECONDS` | `900` | Lifetime of a one-time enrollment code. |
| `DEVICE_NONCE_TTL_SECONDS` | `86400` | Replay-nonce retention for device-signed requests. |
| `DEVICE_SIGNATURE_MAX_SKEW_SECONDS` | `300` | Accepted clock skew on a device request signature. |

## Events, bookings, kiosk stations and anonymous requests

| Variable | Default | Notes |
|---|---|---|
| `ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH` | `128` |  |
| `ANONYMOUS_REQUEST_OUTSTANDING_LIMIT` | `50` |  |
| `EVENT_CHECKIN_CLOCK_SKEW_SECONDS` | `300` |  |
| `EVENT_CHECKIN_ROSTER_LIFETIME_HOURS` | `24` |  |
| `EVENT_CHECKIN_ROSTER_MAX` | `1000` |  |
| `EVENT_CHECKIN_SYNC_GRACE_HOURS` | `24` |  |
| `EVENT_CHECKIN_WINDOW_AFTER_HOURS` | `2` |  |
| `EVENT_CHECKIN_WINDOW_BEFORE_HOURS` | `24` |  |
| `EVENT_STATION_PIN_PEPPER` | `''` |  |
| `KIOSK_COMMAND_MAX_AGE_SECONDS` | `8 * 60 * 60` | Oldest offline kiosk command a replay still accepts. |
| `KIOSK_OPERATOR_LEASE_RETENTION_SECONDS` | `7 * 24 * 60 * 60` | How long ended operator leases are kept before cleanup. |
| `KIOSK_OPERATOR_LEASE_TTL_SECONDS` | `8 * 60 * 60` | Lifetime of one staff operator lease on a kiosk Station. |
| `KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS` | `5 * 60` | A claimed replay is released for retry after this long. |
| `KIOSK_REPLAY_CLEANUP_BATCH_SIZE` | `500` | Rows per batch in the nightly replay cleanup. |
| `KIOSK_REPLAY_RETENTION_SECONDS` | `7 * 24 * 60 * 60` | Retention of completed replay commands, unless a review still references them. |
| `KIOSK_STATION_SESSION_TTL_SECONDS` | `12 * 60 * 60` | Lifetime of a kiosk Station session. |

## Install, build and test-only

Consumed by `setup_instance`, the image build, or the e2e seed; never needed at runtime.

| Variable | Default | Notes |
|---|---|---|
| `BUILD_GIT_DESCRIBE` | read outside `settings.py` |  |
| `BUILD_GIT_SHA` | read outside `settings.py` |  |
| `E2E_PASSWORD` | read outside `settings.py` |  |
| `E2E_SEED_ALLOWED` | read outside `settings.py` |  |
| `SETUP_MAKERSPACE_NAME` | read outside `settings.py` |  |
| `SETUP_MAKERSPACE_SLUG` | read outside `settings.py` |  |
| `SETUP_MODULE_PROFILE` | read outside `settings.py` |  |
| `SETUP_SUPERADMIN_EMAIL` | read outside `settings.py` |  |
| `SETUP_SUPERADMIN_PASSWORD` | read outside `settings.py` |  |
| `SETUP_SUPERADMIN_USERNAME` | read outside `settings.py` |  |
