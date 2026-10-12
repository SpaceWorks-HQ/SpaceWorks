# Environment reference: operations

See [environment-reference.md](environment-reference.md) for core, storage and sign-in settings.

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
