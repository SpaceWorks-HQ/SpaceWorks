# w6-updates: coordinator handoff

## Implemented

- Deployment stable/beta setting (stable default), bounded published-release filtering, plain-text changelog.
- Timed RUNNING detection (two hours by default), host-lock proof, FAILED recovery and exactly-once audit.
- Verified archive/previous-version linkage before image changes; failed snapshots cancel installation.
- Confirmed superadmin rollback intent through the existing restore service, typed refusals and restore-diff UI.
- Legacy host handoff retains durable intent across DB replacement and starts matching images without migrations.
- Module-off 400, explicit source-gate exemptions for global recovery/restore intent, OpenAPI refusal schemas.
- Self-review fixes: compound-envelope refusal even with partial=false, image/control ordering, quarantine writers,
  singleton admin identity, rollback retries/idempotency, frontend polling and explanatory refusal details.

## Remaining: rollback is NOT complete for current deployment archives

- The existing builder always emits a Lane E compound envelope. Its outer manifest lacks the legacy object
  ledger. restore.sh is a legacy supervisor; treating this envelope as legacy would silently omit objects.
- Product rollback therefore refuses compound snapshots with snapshot_unsupported. The existing Python
  run_compound_restore coordinator has no shipped host invocation/adapters connecting an update intent.
- A coordinator/host restore lane must wire that existing compound path (with its H1 admission, sibling DB,
  object/authority fences and pointer protocol). Do not bypass it or claim this lane delivers new-snapshot rollback.
- Single-box restore also remains refused because the existing restore supervisor requires bundled topology.

## Decisions and scope

- No new module, feature key, model or accounts.User FK. This is deployment policy/state on an existing singleton.
- Existing data_export classification omits updates.PlatformUpdateSettings; the tenant model catalog derives its
  drop rule from that classification. The literal field snapshot now covers all added fields. No tenant authority travels.
- No owner product decision is needed for assigned stable/beta behavior: the brief explicitly requests both.
- Version hold/pinning, migration-compatibility CI and beta publishing pipelines were not requested and are omitted.

## Validation

- No database, host-behavior or frontend test suite was run; no test success is claimed.
- TypeScript compilation: npm exec tsc -- -b --pretty false exited 0.
- Python AST parsing, Bash syntax checks and git diff --check completed without reported errors.
- All changed files inspected for UTF-8 without BOM, LF, mojibake and <=300 lines; AGENTS/CLAUDE identical.
- codex doctor still reports provider reachability/desktop diagnostic failures; CLI review unavailable.
- The index remains empty. No state-changing git commands or generated OpenAPI edits were performed.

## Migration

- backend/apps/updates/migrations/0002_update_recovery.py depends on updates.0001_initial and
  backup.0026_backfill_backup_module (actual directories inspected). It backfills running_since from updated_at.

## Coordinator checks

- Run the new/expanded tests below, existing test_platform_updates.py and test_platform_updates_recovery.py,
  test_privileged_script_modes.py, data_export/test_registry_guards.py,
  tenant_migration/test_tenant_dump_catalog_d1.py and test_source_gate_guards.py, and backup restore regressions.
- Generate the OpenAPI snapshot and frontend API types centrally.
- Verify host capability installation after changing restore.sh: the existing capability record hashes that script.
- Existing git modes: restore.sh=100755; update.sh=100644. The latter is inherited; coordinator must record
  update.sh as executable when staging, as required by the brief. New update-rollback.sh is sourced, not directly executed; no mode was staged.
- Outside-task defect: current compound archive production and the legacy host supervisor are not connected,
  including an outer envelope with partial=false. Existing supervisor can misroute it into legacy handling.

## File inventory

- Created: `LANE-PROGRESS.md`
- Created: `backend/apps/admin_api/serializers_platform_updates.py`
- Created: `backend/apps/admin_api/views_update_recovery.py`
- Created: `backend/apps/updates/errors.py`
- Created: `backend/apps/updates/migrations/0002_update_recovery.py`
- Created: `backend/apps/updates/recovery.py`
- Created: `backend/apps/updates/releases.py`
- Created: `backend/apps/updates/rollback.py`
- Created: `backend/tests/test_host_update_rollback.py`
- Created: `backend/tests/test_platform_update_channels.py`
- Created: `backend/tests/test_platform_update_rollback.py`
- Created: `backend/tests/test_platform_update_snapshots.py`
- Created: `backend/tests/test_platform_update_timeout.py`
- Created: `docs/SOURCE-MAP-PLATFORM.md`
- Created: `frontend/src/features/staff/UpdateRecoveryControls.tsx`
- Created: `frontend/src/features/staff/platformUpdateApi.ts`
- Created: `scripts/update-rollback.sh`
- Modified: `backend/apps/admin_api/urls_platform.py`
- Modified: `backend/apps/admin_api/views_platform_updates.py`
- Modified: `backend/apps/tenant_migration/gate_policy_http.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- Modified: `backend/apps/updates/admin.py`
- Modified: `backend/apps/updates/management/commands/update_control.py`
- Modified: `backend/apps/updates/models.py`
- Modified: `backend/apps/updates/services.py`
- Modified: `backend/tests/modules/test_offstate_platform.py`
- Modified: `backend/tests/test_cloud_openapi_errors.py`
- Modified: `backend/tests/test_host_updater_behavior.py`
- Modified: `backend/tests/tombstone/test_updates_removed_surfaces.py`
- Modified: `docs/PROJECT-STATUS.md`
- Modified: `docs/SOURCE-MAP.md`
- Modified: `frontend/src/features/staff/BackupRestorePanel.tsx`
- Modified: `frontend/src/features/staff/PlatformUpdatePanel.test.tsx`
- Modified: `frontend/src/features/staff/PlatformUpdatePanel.tsx`
- Modified: `frontend/src/features/staff/StaffPlatformTabContent.tsx`
- Modified: `scripts/restore.sh`
- Modified: `scripts/update.sh`

## Added tests (all pending coordinator execution)

- `backend/tests/test_host_update_rollback.py`
  - `test_completed_rollback_hands_off_and_restarts_without_migrations`
  - `test_paused_restore_keeps_durable_intent_and_releases_updater_lock`
  - `test_quarantined_rollback_does_not_start_normal_writers`
  - `test_resume_uses_host_intent_after_the_database_pointer_is_lost`
  - `test_single_box_refuses_before_restore_or_image_changes`
  - `test_terminal_refusal_keeps_current_images_and_does_not_repeat_restore`
- `backend/tests/test_platform_update_channels.py`
  - `test_beta_includes_prereleases_and_stable_releases_in_publication_order`
  - `test_beta_tag_cannot_enter_stable_even_with_a_mislabelled_prerelease_flag`
  - `test_channel_cannot_change_during_an_update`
  - `test_channel_switch_clears_notes_and_version_and_is_audited`
  - `test_control_add_keeps_the_singleton_identity_for_django_logging`
  - `test_control_channel_change_uses_locked_state_and_audits_fields_only`
  - `test_host_command_selects_and_records_notes_from_json_without_shell_interpolation`
  - `test_malformed_or_unfinished_releases_are_not_installed`
  - `test_release_note_links_are_restricted_to_the_project_release_page`
  - `test_release_notes_are_cached_with_the_exact_version_and_no_display_prefix`
  - `test_stable_is_default_and_filters_drafts_and_prereleases`
  - `test_unknown_channel_is_validated_at_the_serializer_boundary`
- `backend/tests/test_platform_update_rollback.py`
  - `test_active_rollback_blocks_channel_change_and_host_claim`
  - `test_an_untracked_previous_image_refuses_rollback`
  - `test_another_active_restore_is_refused_by_the_existing_service`
  - `test_completed_rollback_cannot_be_requested_again`
  - `test_failed_or_aborted_rollback_can_be_requested_again`
  - `test_legacy_database_only_backup_has_a_typed_no_snapshot_refusal`
  - `test_restore_boundary_refusal_does_not_write_the_update_link_or_audit`
  - `test_rollback_refuses_an_update_in_progress`
  - `test_rollback_refuses_unavailable_unverified_and_compound_snapshots`
  - `test_rollback_requires_confirmation_fields_at_the_boundary`
  - `test_rollback_requires_confirmation_of_the_exact_displayed_restore_point`
  - `test_rollback_uses_the_existing_restore_boundary_and_is_idempotent`
  - `test_rollback_with_the_real_request_service_only_records_intent_and_both_audits`
- `backend/tests/test_platform_update_snapshots.py`
  - `test_recovered_or_changed_update_cannot_attach_a_late_snapshot`
  - `test_snapshot_cannot_be_taken_without_a_claimed_update`
  - `test_snapshot_failure_does_not_offer_an_older_updates_archive`
  - `test_snapshot_uses_the_backup_builder_boundary_and_links_only_a_completed_archive`
- `backend/tests/test_platform_update_timeout.py`
  - `test_a_live_or_inaccessible_host_lock_refuses_timed_recovery`
  - `test_configured_timeout_and_nonrunning_states`
  - `test_get_reports_stuck_without_mutation_or_releasing_any_lock`
  - `test_host_claim_recovery_is_also_audited_with_a_system_actor`
  - `test_module_off_actions_return_typed_400`
  - `test_new_update_actions_refuse_managers_and_anonymous_callers`
  - `test_new_update_actions_require_an_active_unrestricted_rotated_superadmin`
  - `test_recent_running_update_cannot_be_recovered_and_never_touches_the_host_lock`
  - `test_recovery_rechecks_state_after_acquiring_the_host_lock`
  - `test_stuck_detection_uses_the_started_time_and_strict_timeout`
  - `test_timed_recovery_is_idempotent_audited_and_releases_the_logical_lock`
  - `test_unrelated_settings_write_does_not_restart_the_update_timeout`
- `backend/tests/modules/test_offstate_platform.py`
  - Expanded existing module-off or tombstone cases for the updated/new routes.
- `backend/tests/test_cloud_openapi_errors.py`
  - `test_update_refusals_document_a_typed_reason_and_detail`
- `backend/tests/test_host_updater_behavior.py`
  - `test_snapshot_failure_cancels_before_images_or_migrations_change`
- `backend/tests/tombstone/test_updates_removed_surfaces.py`
  - Expanded existing module-off or tombstone cases for the updated/new routes.
- `frontend/src/features/staff/PlatformUpdatePanel.test.tsx`
  - saves the selected release channel and displays release notes as text
  - renders untrusted release HTML without executing it
  - lets a stuck update be recovered and shows the recorded failure
  - requires both rollback confirmations and submits the displayed restore point
  - shows missing snapshot information without offering a destructive action
