# LANE-PROGRESS - backup completion pass

All edits are inside this worktree and unstaged. No state-changing git commands were run.
The main-checkout audit and plan were read but not edited. Their after-lane table and this
lane's former progress notes disagreed: recovery-command tests and file-backed streaming
promotion were already present on entry. This pass strengthens them rather than duplicating them.

## Completed
- Audit 10: expanded recover_superadmin command coverage for generated/explicit passwords,
  missing accounts, disabled principals, durable identity, quarantine and secret-free audit.
- Streaming promotion: bounded 1 MiB reads into a private seekable temporary file; source
  connection closed before PUT; explicit content length; If-None-Match remains create-only.
  Added deterministic stream/rewind/failure/conflict regressions alongside existing MinIO tests.
- Audit 8/19: expanded rollback retention tests; archive pruning now deletes both staging
  layouts plus recorded staging locators, and retries failed staging cleanup without expiring
  or deleting the archive row. Existing starvation/audit fixes remain.
- Audit 16/25: checked the module registry (34 keys), default-on backfill, profiles,
  docs/MODULES.md, contract probe, sovereignty coupling, classification/catalog entries and
  frontend module visibility. Added module-off mutation and custody-scoping regressions.
  Module purge now also collects staging keys and cleans crashed-attempt prefixes after commit.
- Audit 24: destination/journal lists now use DRF's 24-row pagination with documented schemas;
  manual push returns 503 if dispatch fails. Shared audited retire/probe services now back
  API and /control/ actions; admin forms share API validation and never prefill secrets.
  Location edits are refused once journal rows exist, preserving existing copy addresses;
  credential rotation and disabling remain supported. Unreadable credentials yield a typed
  safe error. Added API/admin/OpenAPI, fan-out, lease fencing, ledger-admission, retention,
  transport-failure, periodic verification and task-isolation coverage.
- Rehydration now verifies a fresh primary staging key, promotes create-only using the shared
  primitive, verifies final bytes and cleans the staging attempt. Added corrupt-copy/race tests.
- Fresh-host fetch validates credentials/index shapes, preserves existing files, and emits
  a private local index of verified facts alongside the archive. Signature preflight remains
  the authenticity check. External rehydration errors no longer log provider tracebacks.
- Audit 21: added backup-job scheduler invocation/due-only coverage for the all-in-one cron,
  plus image/launcher wiring coverage. This is not a host/image end-to-end restore exercise.
- Split the near-ceiling recipient views into enrollment/lifecycle/common modules with an
  explicit compatibility barrel; updated docs/SOURCE-MAP.md.

## Validation performed here
- Python AST parsing for every changed Python file; all are within the 300-line ceiling.
- git diff --check; AGENTS.md and CLAUDE.md remain byte-identical and unchanged.
- No database, MinIO, Docker, frontend or host tests were run in this pass. Earlier test
  results from the inherited progress file are not validation of these changes.
- No OpenAPI/generated TypeScript snapshots regenerated; coordinator owns regeneration.
- No new models, feature keys, module keys or migrations. Existing backup migration leaf
  checked: 0026_backfill_backup_module (depends on backup/0025 and makerspaces/0072).

## Remaining / owner decisions
- True restore drills: host age identity and drill policy (audit 18), per plan.
- K1 makerspace archive import: product decision (audit 12); Lane D is the supported path.
- Lane D HTTP/CLI orchestration (audit 13): owner decision / other lane, untouched.
- Full all-in-one host/image end-to-end exercise: deferred by plan; requires host stack.
- Phase D2 Postgres replica: explicitly out of scope in the plan.
- Coordinator must run the tests and regenerate API snapshots before integration.
- The staff-console destination-management placement is unchanged: the plan assigns
  management to API and /control/, and only module visibility to the staff Backups tab.

## Outside-scope defects noticed
- docs/INVARIANTS.md's older Modules are OPT-IN paragraph still gives stale default-enabled
  keys/counts; the actual registry now defaults updates and backup on (audit's known defect).
- Lane D tenant exit still lacks orchestration (audit's known defect; owner decision above).
- The existing scheduler test test_a_failed_task_is_still_due_next_run does not actually
  execute a failure, and its immediate-retry comment disagrees with the runner's documented
  at-most-once claim-before-execution behavior. No scheduler policy changed here.

## Coordinator test commands
Run the isolated runner against THIS worktree, without another pytest or review process:

```bash
./scripts/dev.sh test tests/backup tests/modules tests/makerspaces
./scripts/dev.sh test tests/data_export/test_registry_guards.py tests/tenant_migration/test_tenant_dump_catalog_d1.py tests/test_scheduled_tasks.py
```

Also run the existing frontend BackupRestorePanel.test.tsx and regenerate the OpenAPI and
TypeScript snapshots; destinations and journal now return paginated envelopes.

## Files changed in this pass
- `backend/apps/backup/admin_offsite.py` (modified)
- `backend/apps/backup/management/commands/fetch_offsite_archive.py` (modified)
- `backend/apps/backup/offsite_client.py` (modified)
- `backend/apps/backup/offsite_restore.py` (modified)
- `backend/apps/backup/serializers_offsite.py` (modified)
- `backend/apps/backup/services_access.py` (modified)
- `backend/apps/backup/services_offsite.py` (created)
- `backend/apps/backup/storage_promotion.py` (modified)
- `backend/apps/backup/tasks_offsite.py` (modified)
- `backend/apps/backup/views_offsite.py` (modified)
- `backend/apps/backup/views_recipients.py` (modified)
- `backend/apps/backup/views_recipients_common.py` (created)
- `backend/apps/backup/views_recipients_enrollment.py` (created)
- `backend/apps/backup/views_recipients_lifecycle.py` (created)
- `backend/apps/makerspaces/module_purge_collectors_backup.py` (modified)
- `backend/tests/backup/test_archive_retention_purge.py` (modified)
- `backend/tests/backup/test_backup_module.py` (modified)
- `backend/tests/backup/test_backup_module_surfaces.py` (created)
- `backend/tests/backup/test_backup_singlebox_schedule.py` (created)
- `backend/tests/backup/test_offsite_control.py` (created)
- `backend/tests/backup/test_offsite_fetch_validation.py` (created)
- `backend/tests/backup/test_offsite_jobs.py` (created)
- `backend/tests/backup/test_offsite_rehydration.py` (created)
- `backend/tests/backup/test_offsite_schema.py` (created)
- `backend/tests/backup/test_offsite_surfaces.py` (created)
- `backend/tests/backup/test_recover_superadmin_command.py` (modified)
- `backend/tests/backup/test_storage_promotion_streaming.py` (created)
- `docs/SOURCE-MAP.md` (modified)
- `LANE-PROGRESS.md` (modified; this report)

## Tests added (not executed)

`backend/tests/backup/test_archive_retention_purge.py`
- `test_purge_removes_compound_staging_file_and_recorded_attempt_key`
- `test_retention_never_prunes_an_in_flight_archive`
- `test_rollback_cleanup_only_removes_the_exact_retained_source_version_after_success`
- `test_rollback_cleanup_storage_failure_keeps_the_journal_for_retry`
- `test_staging_cleanup_failure_keeps_the_archive_retryable`

`backend/tests/backup/test_backup_module.py`
- Updated existing purge test to expect the compound staging locator.

`backend/tests/backup/test_backup_module_surfaces.py`
- `test_custody_exposes_both_states_only_to_the_makerspace_manager`
- `test_module_off_refuses_every_tenant_mutation_before_processing_payloads`
- `test_module_purge_cleans_failed_attempt_prefix_after_commit`

`backend/tests/backup/test_backup_singlebox_schedule.py`
- `test_singlebox_cron_reaches_due_backup_reconcile_offsite_and_retention_jobs`
- `test_singlebox_image_has_age_and_runs_the_backup_scheduler_through_cron_admission`

`backend/tests/backup/test_offsite_control.py`
- `test_control_create_and_rotation_encrypt_credentials_and_never_prefill_passwords`
- `test_control_destination_is_superadmin_only_and_journal_is_read_only`
- `test_control_form_validates_the_same_boundaries_as_the_api`
- `test_control_test_and_retire_actions_use_audited_lifecycle_services`

`backend/tests/backup/test_offsite_fetch_validation.py`
- `test_credentials_file_refuses_non_string_values`
- `test_fetch_never_replaces_an_existing_local_file`
- `test_fetch_never_replaces_an_existing_local_index`
- `test_fetch_writes_a_private_local_index_of_the_verified_facts`
- `test_invalid_sidecar_size_refuses_before_creating_a_local_archive`
- `test_non_object_index_is_a_typed_destination_error`

`backend/tests/backup/test_offsite_jobs.py`
- `test_artifact_ledger_is_authoritative_and_disagreement_refuses_the_copy`
- `test_expired_upload_claim_is_retried_and_previous_holder_cannot_commit`
- `test_offsite_task_continues_after_a_step_failure_and_dispatch_is_fail_safe`
- `test_one_destination_failure_does_not_prevent_another_from_verifying`
- `test_retention_and_reverify_transport_failures_preserve_verified_facts`
- `test_retention_keeps_newest_deployment_and_each_tenant_on_every_destination`

`backend/tests/backup/test_offsite_rehydration.py`
- `test_a_primary_copy_reappearing_after_admission_is_never_overwritten`
- `test_corrupt_offsite_copy_cannot_reach_primary_staging`
- `test_expired_archive_is_refused_even_when_an_offsite_copy_survives`
- `test_rehydration_verifies_staging_then_final_and_removes_the_attempt_key`

`backend/tests/backup/test_offsite_schema.py`
- `test_offsite_routes_have_authenticated_request_response_and_error_schemas`

`backend/tests/backup/test_offsite_surfaces.py`
- `test_destination_list_is_paginated_and_rotated_credentials_stay_write_only`
- `test_destination_location_cannot_move_after_journaling_but_credentials_can_rotate`
- `test_every_destination_surface_refuses_non_superadmins`
- `test_journal_pages_reach_beyond_the_old_hundred_row_cutoff_and_are_destination_scoped`
- `test_manual_push_reports_dispatch_failure_and_audits_the_request`
- `test_probe_turns_unreadable_credentials_into_a_safe_audited_error`
- `test_rehydration_api_dispatches_an_admitted_request_and_audits_user`
- `test_retired_destinations_cannot_be_reenabled_or_tested_and_keep_the_journal`

`backend/tests/backup/test_recover_superadmin_command.py`
- `test_explicit_password_recovers_a_disabled_admin_without_acknowledging_quarantine`
- `test_generated_password_is_the_password_actually_installed`
- `test_unknown_username_cannot_create_a_recovery_account`

`backend/tests/backup/test_storage_promotion_streaming.py`
- `test_conditional_conflict_is_typed_and_closes_both_streams`
- `test_nonseekable_source_streams_in_bounded_chunks_to_a_rewindable_put`
- `test_stream_failure_closes_the_source_and_never_publishes`
