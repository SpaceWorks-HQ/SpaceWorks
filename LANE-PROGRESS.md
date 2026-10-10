# Lane 7c handoff ? implementation complete, runtime verification pending

Built on the existing 7b ledger; all changes remain unstaged. No state-changing git
commands or database tests were run. AGENTS.md/CLAUDE.md remain byte-identical.

## Completed
- Read root instructions, global workflow, phase 7c plan/review/reference diff,
  relevant invariants and actual 7b/QR/export/movement implementations.
- LabelPrintCommand and immutable LabelPrintResult receipt models; 0003 migration
  with request/operation uniqueness, completion constraints and SQL claim guards.
- MANAGE_QR send/reprint and paginated history; same-tenant active label devices;
  transactional DRAFT-to-PRINTED freeze and payload-sensitive staff idempotency.
- Extended 7b services_commands, serializer and URLs for labels. Shared leases,
  acknowledgements, key-version ownership and one extracted backoff calculation.
- Signed content/result endpoints use canonical in-memory ZIP of SVGs. Fixed result
  code/messages, immutable operation receipts and bounded retries preserve replay.
- Audit uses User for staff and None for devices with typed IDs and DeviceEvents;
  shared lease/ack provenance also carries label/batch IDs. No QR contents or bytes.
- Frozen batch service and /control/ editor; admin domain split retains explicit
  re-exports. Asset generation takes tenant lock before product/batch/quota locks.
- New *_7c siblings unioned into export/User/dataset/origin/purge/catalog/snapshot/
  authority/projection/uniqueness/audit registries. Import cancels shared commands,
  clears lease/ack ownership and preserves receipt/source snapshot history.
- Combined catalog pin reconstructed after reproducing 7b baseline exactly:
  d491cbdde52737edca2e8c014688c2883729d0686e6d1bac798d12cd905d2b4b.
- Protocol/invariant documentation in docs/device-label-commands.md; SOURCE-MAP link.

## Coordinator work remaining
- Run focused label/device and QR operations tests below, including concurrency;
  then existing tests/devices, tests/operations, tests/data_export,
  tests/tenant_migration, tests/makerspaces, tests/backup and registry guards.
- Run the full isolated suite via scripts/dev.sh test and the existing eleven-app
  tombstone profile separately. Never share a DB between pytest processes.
- Run manage.py check, makemigrations --check --dry-run, schema validation and
  validate_catalog against loaded Django models to verify the reconstructed pin.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts.
- Complete independent coordinator review/QA and commit; lane performed no staging.

## Verification performed (no tests run)
- codex doctor: home/config unavailable and required inference endpoint unreachable;
  nested CLI review remains blocked, not claimed complete.
- Python Django import: package unavailable. Docker/Postgres inaccessible as stated.
- AST parse, project import/symbol resolution and <=300-line checks: no findings.
- New model/migration/export/tenant-catalog field sets agree; mirror drift guard empty.
- Static catalog reconstruction reproduced the 7b baseline pin before adding 7c.
- Read-only git diff/status/index checks; git diff --check had no whitespace errors.

## Migration
- backend/apps/devices/migrations/0003_label_commands.py depends on the actual
  devices.0002_printer_jobs and operations.0009_report_schedules leaves, plus
  migrations.swappable_dependency(settings.AUTH_USER_MODEL).
- _label_guards.py is its SQL helper, not an additional migration.

## Deliberate skips / owner decisions / observations
- No owner product decisions needed; the reviewed plan defaults were used.
- Staff UI (7d), PDF/raster/CUPS/IPP/agent packaging and generated API artifacts
  remain deferred by task scope. No module, feature, role or action key was added.
- No edits to >300-line docs/INVARIANTS.md or docs/MODULES.md: this lane's hard
  ceiling prevents touching them. Standalone label documentation and SOURCE-MAP
  carry the complete contract; no new module key requires a MODULES entry.
- Archive/object ownership/storage/encryption/reference closure registries reviewed
  without label changes: no persisted bytes, object fields, free-form PII, movable
  cross-tenant target or semantic raw User IDs exist in the new models.
- Found and fixed the existing QR admin inline/status bypass of post-send freeze.
- Runtime suites, migration/schema checks and independent review remain unverified.
- Existing qr_zip has no batch size limit; preserves that behavior. This is an
  outside-scope resource-bound observation, not a newly claimed protection.
- Existing shared delivery locks enter the printer PII fence for label polling too;
  preserved 7b's ownership boundary. Label reports/content hold no new PII.

## Every created or modified file
- LANE-PROGRESS.md
- backend/apps/data_export/classification.py
- backend/apps/data_export/classification_7c.py
- backend/apps/data_export/datasets.py
- backend/apps/data_export/datasets_7c.py
- backend/apps/data_export/references.py
- backend/apps/data_export/references_7c.py
- backend/apps/devices/admin.py
- backend/apps/devices/admin_labels.py
- backend/apps/devices/errors_labels.py
- backend/apps/devices/label_access.py
- backend/apps/devices/migrations/0003_label_commands.py
- backend/apps/devices/migrations/_label_guards.py
- backend/apps/devices/models.py
- backend/apps/devices/models_events.py
- backend/apps/devices/models_labels.py
- backend/apps/devices/route_registry.py
- backend/apps/devices/route_registry_7c.py
- backend/apps/devices/serializers_commands.py
- backend/apps/devices/serializers_labels.py
- backend/apps/devices/services_commands.py
- backend/apps/devices/services_label_commands.py
- backend/apps/devices/services_label_delivery.py
- backend/apps/devices/services_label_events.py
- backend/apps/devices/services_label_results.py
- backend/apps/devices/services_printer_events.py
- backend/apps/devices/urls.py
- backend/apps/devices/urls_7c.py
- backend/apps/devices/views_labels.py
- backend/apps/makerspaces/module_purge_collectors_7c.py
- backend/apps/makerspaces/module_purge_collectors_devices.py
- backend/apps/makerspaces/module_purge_plans.py
- backend/apps/makerspaces/origin_scope_model_lookups.py
- backend/apps/makerspaces/origin_scope_routes_7c.py
- backend/apps/operations/admin.py
- backend/apps/operations/admin_qr_batches.py
- backend/apps/operations/services_qr_assets.py
- backend/apps/operations/views_qr_batches.py
- backend/apps/tenant_migration/audit_references_meta.py
- backend/apps/tenant_migration/audit_references_meta_7c.py
- backend/apps/tenant_migration/catalog_7c.py
- backend/apps/tenant_migration/references_7c.py
- backend/apps/tenant_migration/references_devices.py
- backend/apps/tenant_migration/target_projection.py
- backend/apps/tenant_migration/target_projection_7c.py
- backend/apps/tenant_migration/tenant_dump_authority_7c.py
- backend/apps/tenant_migration/tenant_dump_authority_supplement.py
- backend/apps/tenant_migration/tenant_dump_catalog.py
- backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- backend/apps/tenant_migration/tenant_dump_model_catalog.py
- backend/apps/tenant_migration/unique_values.py
- backend/apps/tenant_migration/unique_values_7c.py
- backend/tests/devices/helpers_labels.py
- backend/tests/devices/test_label_commands.py
- backend/tests/devices/test_label_concurrency.py
- backend/tests/devices/test_label_data_export.py
- backend/tests/devices/test_label_delivery.py
- backend/tests/devices/test_label_gates.py
- backend/tests/devices/test_label_tenant_migration.py
- backend/tests/operations/test_qr_batch_freeze.py
- backend/tests/tenant_migration/authority_expectations_7c.py
- backend/tests/tenant_migration/test_authority_dispositions_d8.py
- backend/tests/tenant_migration/test_target_projection.py
- backend/tests/tombstone/test_label_devices_7c.py
- docs/SOURCE-MAP.md
- docs/device-label-commands.md

## Every new test function (coordinator must run)

backend/tests/devices/helpers_labels.py
- Helper/independent authority expectation module; no test function.

backend/tests/devices/test_label_commands.py
- test_first_send_freezes_batch_and_matching_replay_creates_no_second_command
- test_printed_batch_reprint_uses_new_request_id_and_paginated_listing
- test_invalid_batch_does_not_queue
- test_device_kind_and_status_are_enforced
- test_request_id_conflict_for_another_batch
- test_request_id_conflict_for_another_active_label_device
- test_manage_qr_without_manage_devices_can_send_but_device_only_role_cannot
- test_cross_tenant_device_and_batch_are_not_disclosed
- test_request_claim_cannot_be_rewritten_by_queryset_update
- test_unknown_fields_are_rejected_at_staff_boundary
- test_first_send_rolls_back_command_and_freeze_on_failure
- test_batch_claim_cannot_rebind_or_delete_but_requester_fk_may_null

backend/tests/devices/test_label_concurrency.py
- test_concurrent_duplicate_staff_request_creates_one_command
- test_first_send_serializes_against_relabel
- test_concurrent_same_result_writes_one_receipt_and_one_effect
- test_send_and_asset_generation_keep_tenant_before_batch_lock_order

backend/tests/devices/test_label_data_export.py
- test_label_model_field_dataset_user_and_reference_catalogs_are_complete
- test_export_contains_label_receipts_and_history_without_stored_bytes
- test_label_purge_deletes_immutable_receipts_before_parents_and_keeps_qr_batch
- test_devices_module_purge_removes_labels_before_shared_commands
- test_qr_batch_module_purge_preserves_command_and_receipt_history

backend/tests/devices/test_label_delivery.py
- test_zip_is_exact_existing_svg_batch_with_safe_private_headers
- test_unacknowledged_content_result_and_wrong_token_are_refused
- test_acknowledged_long_print_survives_short_delivery_lease_expiry
- test_success_replay_is_identical_and_conflicting_operation_cannot_finish_twice
- test_retry_receipt_replay_does_not_requeue_or_overwrite_a_later_success
- test_permanent_or_exhausted_failure_is_terminal
- test_late_ack_cannot_cancel_permanent_failure_or_break_result_replay
- test_key_rotation_cannot_reuse_a_previously_acknowledged_label_command
- test_expired_unacknowledged_lease_requeues_then_exhausts
- test_another_signed_device_cannot_fetch_or_report_and_revocation_is_rechecked
- test_purged_batch_cancels_delivery_and_snapshots_cannot_restore_it
- test_purged_acknowledged_batch_commits_cancellation_before_410
- test_result_text_and_unknown_fields_never_enter_receipts_or_logs
- test_result_receipt_is_database_immutable
- test_terminal_label_outcome_is_database_immutable_but_batch_purge_can_null_fk
- test_purged_batch_result_commits_cancellation_without_receipt
- test_generic_lease_and_ack_keep_typed_label_provenance
- test_operation_identity_cannot_be_reused_for_another_label_command
- test_result_provenance_failure_rolls_back_receipt_and_retry
- test_rotated_device_cannot_replay_a_receipt_from_its_previous_key

backend/tests/devices/test_label_gates.py
- test_module_off_returns_400_on_staff_content_and_results
- test_disabled_label_adapter_is_cancelled_by_generic_poll_and_never_resurrects
- test_source_gate_refuses_all_label_writes_without_creating_receipts
- test_staff_origin_scope_reads_batch_pk_and_device_registry_is_exact
- test_openapi_documents_staff_send_signed_zip_and_idempotent_result

backend/tests/devices/test_label_tenant_migration.py
- test_label_tenant_catalog_projection_references_and_unique_rules_are_complete
- test_every_imported_command_is_cancelled_and_lease_ownership_cleared
- test_portable_label_history_remaps_live_edges_preserves_receipts_and_never_prints
- test_raw_dump_cancels_label_parent_but_preserves_terminal_receipt_history

backend/tests/operations/test_qr_batch_freeze.py
- test_non_draft_batch_cannot_add_or_relabel_even_with_a_stale_instance
- test_manual_mark_printed_uses_the_same_freeze_boundary_as_device_send
- test_control_admin_cannot_edit_or_reopen_sent_batch
- test_item_endpoint_emits_audit_only_when_draft_mutation_commits

backend/tests/tenant_migration/authority_expectations_7c.py
- Helper/independent authority expectation module; no test function.

backend/tests/tombstone/test_label_devices_7c.py
- test_label_routes_are_absent_when_devices_are_tombstoned
- test_label_schema_and_admin_are_absent_but_history_tables_remain

Existing tests/tenant_migration/test_authority_dispositions_d8.py and
test_target_projection.py now include the 7c authority/projection expectations;
their existing tests are retained, not newly written.

---

# Lane 7d progress - handoff

## Completed

1. Reviewed the 7d/parent plans, parent review and HANDOVER-CODEX section 7 against lane/7a.
   Review: docs/stage1-p7d.md. It cannot be written to the requested main-checkout path under
   this lane's edit-only-worktree restriction; coordinator must copy it there.
2. Split source-gate HTTP/task/object declarations behind gate_policy.py and staff lazy/platform
   rendering behind StaffTabLoaders.tsx / StaffPlatformTabContent.tsx. Prior policy entries preserved.
3. Added servable/module-filtered, per-tenant source-gated offline scan, row-locked offline/recovery
   events and audited bounded nonce/terminal-enrollment retention. Never-seen activation comes from
   retained enrolled events; reactivation clears old observation state. Heartbeat uses the shared
   record_activity_locked hook. Nonce cleanup retains one extra second for inclusive signature skew.
4. Registered identical one-minute Celery/beatless schedules and devices tombstone filters, plus both
   task/fan-out gate catalogs. Beatless cron must run every minute to obtain one-minute latency.
5. Added selectable devices offline/recovered notification feature, complete default-off channel
   state, MANAGE_DEVICES fallback, active membership filtering, shared push recipients and staff-only
   email/chat templates with credential-free edge snapshots; on-commit delivery fails safe.
6. Added paginated identity/status console with create/rename/threshold/revoke/rotate/reactivate,
   loading/error/retry/empty states, short fingerprints, local one-time enrollment modal and shared
   query invalidation. Secret-bearing mutations return void; modal close clears bearer state.
   Custom device managers can reach the device email-template stream. Device stream module-off is 400; affected email-template endpoints document error response schemas.
7. Extended existing module operational health offline failure classification, preserving device -> mobile.
   Added typed portable audit edges in a new devices_7d registry sibling. No new model/module/action/
   capability/environment setting or field-name snapshot change.
8. Updated invariants, source map, module documentation and explicitly pending status/history.

## Remaining / skipped / decisions

- This worktree contains only 7a. No 7b printer binding/job/command/telemetry APIs and no 7c label
  selectors/send/reprint APIs exist. Printer/command components, needs-review approvals and
  QrBatchDevicePrint child were not built against guessed routes. Integrate sibling lanes, then add
  those components, hook authenticated printer traffic into record_activity_locked and widen tab
  access using their machine/QR-scoped APIs. Identity tab currently requires MANAGE_DEVICES to match 7a.
- Do not edit generated OpenAPI JSON/types here; coordinator regenerates them.
- Both choice-only migrations are explicit drafts because Django is not installed. Coordinator must
  run makemigrations --check, schema validation, DB tests and gated independent review before accepting.
- No owner product decision needed for implemented scope. Adapter UI is a missing lane dependency.
- No git state-changing command, staging, commit, merge or push performed. Every change is unstaged.
- codex doctor: CLI executes, but home/config resolution fails and provider endpoints are unreachable.
  Independent CLI review is blocked in this sandbox; coordinator owns that gate.
- No database tests were run and none are claimed to pass.

## Verification actually performed

- Focused Vitest run: 7 files, 64 tests passed (new device UI/tab/matrix tests plus existing staff-tab,
  organization analytics/governance and member-card navigation tests).
- node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json: exit 0.
- node node_modules/vite/bin/vite.js build: exit 0, 472 modules transformed.
- Python AST parsed every changed Python file; gate-policy dictionary entries compared to HEAD;
  file ceilings checked (only existing accepted settings.py exception); AGENTS/CLAUDE byte parity
  and coordinator-generated-file ownership checked. git diff --check: exit 0 (line-ending warnings).
- After final ASCII text cleanup, the 3 new frontend files were re-run: 15 tests passed; typecheck and Vite build again exited 0.
- Frontend dependencies copied read-only from main checkout into this lane's gitignored node_modules;
  built dist is gitignored and not part of the handoff.

## Migrations

- backend/apps/devices/migrations/0002_offline_event_choices.py -> devices.0001_device_identity.
  AlterField DeviceEvent.event_type choices only; no retained-history data mutation.
- backend/apps/integrations/migrations/0026_device_notifications.py -> integrations.0025_webhook_channel.
  AlterField feature choices on NotificationPreference, NotificationDeliveryLog, NotificationRecipient,
  ChatTemplate; AlterField EmailTemplate.stream choices. No new row/field/model.

## Coordinator test run

Use ./scripts/dev.sh test tests/devices tests/test_scheduled_tasks.py tests/test_email_templates_registry.py
with the isolated runner. Also run notification/email/staff-notification regression suites,
tests/tenant_migration (source-gate/audit/export guards), tests/data_export, tests/operations/report coverage,
tests/tombstone, tests/modules and device backup/restore authority checks. Do not run two suites on one DB.
Run makemigrations --check and spectacular schema validation; regenerate both frontend API artifacts.

## Exact backend test inventory (written, not executed)

- backend/tests/devices/test_device_notifications.py
  - test_devices_catalog_is_complete_selectable_and_default_off
  - test_device_fallback_is_active_manage_devices_staff_in_this_tenant
  - test_explicit_user_selection_matches_email_and_push_and_honors_opt_out
  - test_templates_are_staff_only_validated_and_contain_no_secrets
  - test_notifications_are_on_commit_and_capture_the_state_edge
  - test_default_off_emits_no_external_delivery
  - test_provider_exception_does_not_fail_offline_scan_or_recovery
  - test_device_stream_visible_to_identity_manager_and_hidden_without_module
  - test_choice_migrations_match_runtime_fields
  - test_device_delivery_is_suppressed_if_module_is_disabled_before_commit
  - test_foreign_named_recipient_cannot_receive_device_notification
  - test_device_template_direct_access_with_module_off_is_400
- backend/tests/devices/test_device_report_coverage.py
  - test_health_row_counts_offline_as_failure_and_recovery_as_activity
  - test_recovery_is_not_a_failure_and_other_tenant_is_excluded
  - test_state_edges_have_portable_typed_device_references
- backend/tests/devices/test_offline.py
  - test_threshold_boundary_and_repeated_scan_are_one_edge
  - test_never_seen_active_uses_immutable_activation_event_and_pending_is_ignored
  - test_revoked_device_is_not_marked_offline
  - test_cleanup_is_bounded_terminal_expired_only_and_tenant_scoped
  - test_failed_or_replayed_signed_request_cannot_recover
  - test_cleanup_keeps_nonce_through_inclusive_timestamp_boundary
  - test_reactivation_starts_fresh_observation_window
- backend/tests/devices/test_offline_concurrency.py
  - test_concurrent_scans_and_recoveries_emit_one_edge_each
- backend/tests/devices/test_offline_task.py
  - test_frozen_tenant_is_skipped_and_other_tenant_is_processed
  - test_unservable_and_module_off_tenants_are_excluded
  - test_tombstoned_runtime_does_no_work
  - test_task_and_service_are_declared_and_gate_policy_barrel_is_exact
  - test_beatless_tombstone_filter_removes_device_task
  - test_beat_settings_remove_exact_same_device_task_when_tombstoned
- backend/tests/test_email_templates_registry.py
  - test_registry_declares_all_send_path_keys (existing test updated for two devices staff templates)
- backend/tests/test_scheduled_tasks.py
  - test_device_offline_scan_has_equal_one_minute_cadence
  - test_device_scan_due_only_is_once_per_minute

## Frontend tests added (executed)

- frontend/src/features/staff/panels/DevicesPanel.test.tsx: 7 tests - accessible state/fingerprint,
  token absent from caches/storage/URL and Escape focus restoration, create grant consumption,
  pagination/invalidation, loading/retry, empty/no-selection and revoke confirmation.
- frontend/src/features/staff/devicesTab.test.ts: 7 cases - 5 forbidden action combinations,
  device-manager/superadmin access plus template access, module gate and stable scoped routes.
- frontend/src/features/staff/devicesNotificationMatrix.test.tsx: 1 test - default-off UI and explicit opt-in save.

## Defects noticed beyond the main monitoring flow

- Existing staff-email fallback admitted revoked memberships, unlike native push; corrected with active filter.
- Existing 7a nonce pruning was unbounded and could reopen replay during the inclusive skew boundary;
  removed request-time pruning and added scheduled retention grace/regression.
- Existing email-template surfaces for other disabled streams return 404; left their behavior unchanged.
  The newly introduced devices stream follows required module-off 400 behavior.

## Every created or modified file

- backend/apps/devices/migrations/0002_offline_event_choices.py
- backend/apps/devices/notifications.py
- backend/apps/devices/services_offline.py
- backend/apps/devices/tasks.py
- backend/apps/integrations/email_templates_registry_devices.py
- backend/apps/integrations/email_templates_registry_devices_defaults.py
- backend/apps/integrations/migrations/0026_device_notifications.py
- backend/apps/tenant_migration/audit_references_meta_devices_7d.py
- backend/apps/tenant_migration/gate_policy_http.py
- backend/apps/tenant_migration/gate_policy_objects.py
- backend/apps/tenant_migration/gate_policy_tasks.py
- backend/tests/devices/test_device_notifications.py
- backend/tests/devices/test_device_report_coverage.py
- backend/tests/devices/test_offline.py
- backend/tests/devices/test_offline_concurrency.py
- backend/tests/devices/test_offline_task.py
- docs/stage1-p7d.md
- frontend/src/features/staff/StaffPlatformTabContent.tsx
- frontend/src/features/staff/StaffTabLoaders.tsx
- frontend/src/features/staff/deviceQueryKeys.ts
- frontend/src/features/staff/devicesApi.ts
- frontend/src/features/staff/devicesNotificationMatrix.test.tsx
- frontend/src/features/staff/devicesTab.test.ts
- frontend/src/features/staff/panels/DeviceEnrollmentModal.tsx
- frontend/src/features/staff/panels/DeviceIdentitySection.tsx
- frontend/src/features/staff/panels/DevicesPanel.test.tsx
- frontend/src/features/staff/panels/DevicesPanel.tsx
- LANE-PROGRESS.md
- backend/apps/admin_api/serializers_email_templates.py
- backend/apps/admin_api/views_email_templates_common.py
- backend/apps/admin_api/views_email_templates_space.py
- backend/apps/devices/models_events.py
- backend/apps/devices/services_enrollment.py
- backend/apps/devices/services_events.py
- backend/apps/devices/services_requests.py
- backend/apps/devices/views_heartbeat.py
- backend/apps/integrations/email_templates_registry.py
- backend/apps/integrations/models_email.py
- backend/apps/integrations/notification_catalog.py
- backend/apps/integrations/notification_enums.py
- backend/apps/integrations/recipients_selection.py
- backend/apps/integrations/staff_notifications.py
- backend/apps/operations/management/commands/run_scheduled_tasks.py
- backend/apps/operations/reports_module_health.py
- backend/apps/tenant_migration/audit_references_meta.py
- backend/apps/tenant_migration/gate_policy.py
- backend/config/settings.py
- backend/tests/test_email_templates_registry.py
- backend/tests/test_scheduled_tasks.py
- docs/INVARIANTS.md
- docs/MODULES.md
- docs/PROJECT-HISTORY.md
- docs/PROJECT-STATUS.md
- docs/SOURCE-MAP.md
- frontend/src/features/staff/NotificationRecipientPicker.tsx
- frontend/src/features/staff/StaffTabContent.tsx
- frontend/src/features/staff/staffAccess.ts
- frontend/src/features/staff/staffTabs.ts
