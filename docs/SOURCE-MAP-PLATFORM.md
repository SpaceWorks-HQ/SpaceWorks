# Deployment and backup source map

- `scripts/install-runner.sh` - optional Linux/systemd GitHub Actions runner registration/removal,
  silent short-lived tokens, install-owner service, `spaceworks-prod` label and final GitHub operator steps.
  `scripts/runner-release.py` selects the latest host architecture asset and validates published SHA-256
  checksums before extraction. The runner `.env` records `SPACEWORKS_DIR`.
- `.github/workflows/release.yml` - image and GitHub release publication followed by an opt-in `deploy`
  job on `[self-hosted, spaceworks-prod]`, restricted to main and `SPACEWORKS_DEPLOY=true`. It invokes
  the installed updater for exactly `needs.prepare.outputs.version`, with no checkout or action steps.
- `scripts/update.sh` - portable lock, validated exact/newest GitHub main-release selection, pre-update SQL backup,
  pinned-image deployment, readiness, version marker and automatic application-image rollback.
  `scripts/install-owner.sh` preserves install-owner/sudo re-entry. `scripts/setup-first-run.sh` owns
  guided first-run settings and private `.env` creation. `scripts/spaceworks-compose.sh` validates with
  host Python 3.10+ when available, otherwise in the backend image under the caller's UID/groups.
  Successful runs remove completed migration, orchestration and bucket-creation containers; failures
  preserve them for inspection. Database recovery remains a separate operation.
- `scripts/install-host-bundle.sh` - stages an explicit host runtime bundle on installer upgrades,
  retaining replaced files in `backups/host-config-*`. The updater first verifies its database dump
  and pulls the new backend image, then replaces the bundle and refreshes Compose trust records.
  `scripts/retire-update-polling.sh` removes the former update cron without removing other jobs;
  `scripts/retire-update-tombstone.sh` removes only the retired app label from host configuration.

- `backend/apps/backup/` — deployment backup + restore (Phase 5A/Lane E). `outer_manifest.py` owns the
  signed readable manifest, `artifact_ledger.py` + `models_artifact_ledger.py` own durable component and
  recipient custody, `activation.py` owns the access-switch/activation transition, and
  `artifact_protocol.py`/`promotion.py`/`reconciliation.py` own staged upload and the single availability
  transaction. `services.py` is the stable barrel over archive/access/lease/run lifecycle modules;
  `models_runs.py` + `runs.py` own scheduled-run cohort and coverage proofs, while `services_runs.py`
  orchestrates their serialized builds. Offsite destinations: `models_offsite.py` (destination +
  upload journal), `offsite_client.py` (S3 byte primitives), `offsite_enqueue.py` (eligibility + journal rows), `offsite_push.py` (fan-out + read-back
  verification), `offsite_retention.py`, `offsite_reverify.py` (periodic re-read), `offsite_restore.py` (create-only rehydration),
  `tasks_offsite.py`, `views_offsite.py`, `services_offsite.py` (shared API/admin retirement and probes)
  and the `fetch_offsite_archive` command. `views_recipients.py` explicitly re-exports enrollment and
  lifecycle views; `views_recipients_common.py` owns their scoped lookups and error contracts. `module_gate.py` owns
  the `backup` module key; `views_custody.py` is its read-only custody status.
  `archive_metadata.py` owns stable build/settings manifest facts;
  `backup_control_preflight.py` remains the E9b restore validator behind the `restore_preflight.py`
  compatibility surface. Archive builder, `restore_diff`, the global quarantine
  `middleware.py` + `route_policy.py`, `recovery.py`, `object_restore.py`,
  `operation_lock.py`, and the privileged host scripts (`scripts/restore.sh`, `scripts/import-backup.sh`)
  own verified archive recovery independently of release deployment. Project JWT classes (`accounts/tokens.py`, `token_guard.py`) stamp
  `auth_generation`. `custody.py` is the makerspace-first/recipient-PK serialization boundary;
  `tenant_exit_custody.py` derives Lane D's independent tenant-only floor, while
  `tenant_exit_custody_alarms.py` reuses the decision-19b recipient selectors and parameterized durable
  dispatcher for its retryable outbox. The `host_*` modules own H1's marker, consume-only capability socket,
  signed grant, run ledger, supervisor and atomic pointer; `database_grants.py` is its independent
  PostgreSQL role boundary. `cloud_environment.py` captures host-rendered Cloud Compose interpolation into
  durable static configuration without consulting later ambient shells; only the root-only
  `scripts/init-cloud-environment.py` renderer invokes Compose.
