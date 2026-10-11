# Platform update and backup source map

- `backend/apps/updates/` — singleton deployment update state. `releases.py` selects published stable/beta
  releases and caches plain-text changelogs; `recovery.py` checks the running timeout and shared host
  lock before audited recovery; `rollback.py` binds snapshots and confirmed intent to the existing
  restore service. `services.py` owns host claims and check/backup/result state.
  `admin_api/serializers_platform_updates.py`, `views_platform_updates.py` and
  `views_update_recovery.py` expose superadmin-only settings, recovery and rollback.
  `update_control` drives the privileged host scheduler; the web never receives a Docker socket.
  `scripts/update-rollback.sh` is sourced by `update.sh` to hand supported legacy snapshots to
  `restore.sh` with previous immutable images. Compound envelopes are refused, including an envelope
  with no sovereign slices: the existing legacy supervisor cannot restore their object ledger.
  The staff `PlatformUpdatePanel`, `UpdateRecoveryControls` and hand-written `platformUpdateApi`
  show release notes, confirmations and the existing restore-diff decision.
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
  that mirror `apps/updates`. Project JWT classes (`accounts/tokens.py`, `token_guard.py`) stamp
  `auth_generation`. `custody.py` is the makerspace-first/recipient-PK serialization boundary;
  `tenant_exit_custody.py` derives Lane D's independent tenant-only floor, while
  `tenant_exit_custody_alarms.py` reuses the decision-19b recipient selectors and parameterized durable
  dispatcher for its retryable outbox. The `host_*` modules own H1's marker, consume-only capability socket,
  signed grant, run ledger, supervisor and atomic pointer; `database_grants.py` is its independent
  PostgreSQL role boundary. `cloud_environment.py` captures host-rendered Cloud Compose interpolation into
  durable static configuration without consulting later ambient shells; only the root-only
  `scripts/init-cloud-environment.py` renderer invokes Compose.
