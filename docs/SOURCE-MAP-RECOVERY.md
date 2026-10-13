# Recovery and tenant migration source map

This is the recovery reference linked by [SOURCE-MAP.md](SOURCE-MAP.md).
Update it with code moves; the repository tree remains authoritative.

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

- `backend/apps/tenant_migration/` — per-makerspace migration, managed → self-host (Phase 5B), in
  `SEPARABLE_APPS`. `source_gate.py` + `gate_locks.py`/`gate_runtime.py`/`gate_policy.py`/`middleware.py`/
  `task_gate.py` (the write-drain lock protocol and its AST coverage guards in `source_gate_guards.py`);
  `archive_envelope.py` + `object_export.py` (streamed into `age`); `admission.py` (the source-superadmin
  closure approval); `materialization.py` + `raw_repository.py` + `row_planning.py`/`row_dispositions.py`
  (one-shot insertion); `target_projection.py` (barrel over `target_projection_{types,fields,rows,references}.py`)
  + `unique_values.py` (barrel: the rules dict is
  `unique_values_core.py`, the disposition/policy types `unique_values_policy.py`) + `closure_references.py`;
  `tenant_dump_model_catalog.py` + `tenant_dump_field_snapshot.py` +
  `tenant_dump_authority.py` (public barrel over literal `tenant_dump_authority_entries.py`
  and domain supplements)/`tenant_dump_catalog.py` (Lane D's deny-by-default source catalog), and
  `tenant_dump_source_projection.py` (single-makerspace raw rows plus decision-22 grant closure);
  `tenant_dump_builder.py` (Lane D's migrated scratch → verified custom-dump orchestrator), with
  `tenant_dump_database.py`, `tenant_dump_graph.py`, `tenant_dump_raw.py`, `tenant_dump_sql.py` and
  `tenant_dump_verification.py` owning run-scoped databases, actual-row FK ordering/nullable cycles,
  reviewed raw columns, fence/closure SQL and restored-candidate verification respectively;
  `tenant_dump_sequences.py` owns Lane D's exact empty/non-empty sequence state;
  `tenant_dump_machine_types.py` resolves only fingerprint-identical global built-ins, while
  `tenant_dump_objects.py` packages immutable staged object bytes without live-storage reads;
  `tenant_dump_capture.py` + `tenant_dump_capture_database.py` freeze the full exported-snapshot database
  and exact object bytes before `source_gate_release.py` performs the fenced `copy_capture` release;
  `tenant_dump_staging.py` + `tenant_dump_database_cleanup.py` own marker-guarded crash cleanup;
  `tenant_dump_cleanup.py` retries refused unpublished-object deletion from its durable capture-row key;
  `tenant_dump_derivation.py` derives and seals output only from that capture;
  `tenant_dump_pii.py` binds raw mapped-column mode findings and ciphertext AAD identities;
  `tenant_dump_key_inventory.py` freezes and exact-set checks source-broker key facts, while
  `tenant_dump_dek_protocol.py`/`tenant_dump_dek_helper.py`/`tenant_dump_deks.py` keep plaintext DEKs inside
  the bounded child operation and emit only the tenant-recipient ciphertext;
  `tenant_dump_recipients.py` keeps `outer_recipients` and `tenant_dek_recipients` distinct, and
  `tenant_dump_envelope.py` owns the declared key-member presence/absence ledger plus streaming outer seal;
  `tenant_dump_target.py` binds D5's pre-destructive identity proof to reconstruction, with
  `tenant_dump_target_identities.py` enforcing read-only mode-0600 tenant mounts,
  `tenant_dump_target_protocol.py`/`tenant_dump_target_helper.py`/`tenant_dump_target_deks.py` owning the
  key-free parent plus bounded target decrypt/rewrap child, and `tenant_dump_target_readiness.py` rebuilding
  target search derivations and authenticated readiness; `tenant_dump_target_custody.py` re-proves carried
  recipient public metadata and independently derives Part A versus Lane D custody and decision-19b routing;
  `tenant_dump_manifest.py` and `tenant_dump_lineage.py` bind D4 custody facts and parent/policy digests;
  `tenant_dump_publication.py` owns recipient revalidation, refusal cleanup and the atomic
  pending-to-published/download transition; `tenant_dump_audit_anchors.py` supplies the fail-closed
  external-anchor absence proof;
  `tenant_restore_orchestrator.py` is the D7 §5.4 ordered target-restore spine over H1;
  `tenant_restore_activation.py` owns crash-safe pointer/marker re-entry and writer restart, with
  `tenant_restore_preflight.py`, `tenant_restore_database*.py`, `tenant_restore_sibling.py`,
  `tenant_restore_pgpass.py`, `tenant_restore_pointer.py` and `tenant_restore_scheduler.py` owning
  topology/privilege/lifecycle/credential-minimization/CAS/callback refusal boundaries;
  `tenant_restore_target_state.py`, `tenant_restore_objects.py`, `tenant_restore_api_clients.py`,
  `tenant_restore_superadmin.py` and `host_credential_delivery.py` own target-import gating, pre-ledgered
  object effects, approved authority reset and durable one-time credential delivery;
  `verification.py` (pre-commit), audit-reference domains behind the `audit_references.py` barrel, and
  `target_cutover.py` (pre-activation + `IMPORTING → ACTIVE`);
  `receipts.py`/`receipt_crypto.py`/`cutover.py` (signed single-use handoff); `views_*.py` (superadmin REST).
