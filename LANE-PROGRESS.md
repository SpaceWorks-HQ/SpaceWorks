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
