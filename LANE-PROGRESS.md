# Lane 7b handoff — implementation complete, runtime verification pending

Implemented durable printer bindings, command delivery, typed measured reports, scoped staff approval, telemetry precedence, provenance and movement/purge support. No state-changing git commands were used; all changes are unstaged, and the index is empty. AGENTS.md/CLAUDE.md were not edited.

The key Django/DRF boundary is two transactions: claim immutable validated measurements first, then invoke the existing machine workflow with its stock/charging behavior and commit the applied marker plus provenance together. A failed application rolls back effects and records review separately. Device effects have actor=None; approving staff supply their User. Staff query scope combines MANAGE_DEVICES with the existing machine scope. Automatic application defaults false.

## Completed

- Reviewed the named phase/overview/review/handover documents and actual 7a tree; the corrected review is stage1-p7b.md.
- Four models, field/uniqueness/measurement constraints, report immutability and PII fence triggers; model/admin barrels.
- Signed exact lease/ack/telemetry/result registry and nine OpenAPI-documented device/staff routes; paginated lists and matching detail scope.
- Key-version pins, bounded expiry/backoff, durable ack, replay hashing, manual/automatic application and full rollback of effect/marker/provenance failures.
- New *_7b registry siblings for export/User closure, PII, origin scope, purge, tenant catalog/projection/uniqueness/snapshots/typed audit IDs. Both portable and raw dump conditional resets work.
- Operator and server protocol documentation; default settings 60 seconds / 10 attempts.
- 50 new test functions (parameterized cases add coverage), plus independent authority expectations and existing encryption count/authority guard assertions.

## Validation actually performed

- AST parsing, changed-file project import-name resolution, migration expression-name checks, and <=300 lines for every touched Python file except the accepted settings.py exception. No Django/database imports in these static checks.
- Pure registry construction: nine authority entries, two uniqueness rules, 25 source PII fields / 29 total.
- Reconstructed the literal catalog graph and reproduced the original pin ecf31fe141aba2bf4c273a1043b2cac9440e8ceff9519bc8d3a7218f200efb02 before adding the four independent schemas; resulting pin 5d28998a7fa761b7c83e1d2041ca621fa9d707bffb21337cfe6d82dbb74617e9. Coordinator must verify it against Django models.
- git diff --check completed cleanly; index inspection showed no staged changes.
- No tests were run. Django is not installed in this lane, Docker/Postgres are unavailable, and codex doctor reports unavailable configuration/home and unreachable inference. No test is claimed passing. Temporary lane-only verification scripts are removed from the handoff.

## Migration

- backend/apps/devices/migrations/0002_printer_jobs.py (manually authored historical schema; coordinator must run migration drift checks).
- Dependencies: devices.0001_device_identity; machines.0024_certifications; encryption.0007_tenant_import_fence_operation; migrations.swappable_dependency(settings.AUTH_USER_MODEL). Actual leaves were listed before writing.
- _printer_claim_guards.py is a SQL helper imported by 0002, not another migration.

## Coordinator work remaining

1. Copy stage1-p7b.md to C:/Users/shaan/Music/SpaceWorks/SpaceWorks/docs/plans/2026-09-03-forward-plan/reviews/stage1-p7b.md. The lane-only write rule forbids writing the requested main-checkout path here.
2. Run python manage.py check and python manage.py makemigrations --check --dry-run in the configured backend environment; validate the actual tenant dump catalog digest.
3. Use ./scripts/dev.sh test tests/devices for the focused tests. Run existing machine workflow/consumption/metering/payment tests and tests/data_export, tests/tenant_migration, tests/encryption, tests/makerspaces, tests/backup and tests/test_env_surface_drift.py, then the prescribed full isolated suite. Never share a database between pytest processes or run full pytest concurrently with Codex review.
4. Run tests/tombstone under the existing full eleven-app tombstone profile; it includes the new test_printer_devices_7b.py.
5. Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts (deliberately untouched here), perform the independent review/QA gates, resolve any runtime findings, and coordinate sibling-lane migration/registry integration.

## Skips, decisions and outside defects

- No owner product decision is needed. The plan default is manual review with auto-application false.
- Frontend UI, scheduler/offline work, OctoPrint/Moonraker packaging, label commands and public status remain outside 7b as stated in the plan. No module, feature or role keys were added.
- test_env_surface_drift.py already has 299 lines and no literal device-key pin. New exact default/policy/env-example assertions live in test_printer_settings.py; the existing scanner still covers policy drift.
- No API-client registry, report schema, storage-object catalog or existing machine workflow code was changed. New live FKs use ordinary tenant remapping; only the source snapshot columns need extra semantic declarations.
- Existing Compose maps do not forward device tuning keys, including 7a settings. Shipped defaults and direct backend process environment overrides work; root .env tuning alone is not forwarded. Compose wiring is outside this plan table and remains coordinator work.
- Existing MachineServiceRequest.reason and reserved-pool adjustment reason storage are plaintext. The reused fail workflow keeps that behavior; the new PrinterJob failure copy is encrypted and adapter audit/log metadata contains no free-text reason.

## Every created/modified file

- modified: .env.example
- modified: .env.production.example
- modified: LANE-PROGRESS.md
- modified: backend/.env.example
- modified: backend/apps/backup/settings_policy.py
- modified: backend/apps/data_export/classification.py
- modified: backend/apps/data_export/datasets.py
- modified: backend/apps/data_export/fields.py
- modified: backend/apps/data_export/guards.py
- modified: backend/apps/data_export/references.py
- modified: backend/apps/devices/admin.py
- modified: backend/apps/devices/checks.py
- modified: backend/apps/devices/models.py
- modified: backend/apps/devices/models_events.py
- modified: backend/apps/devices/route_registry.py
- modified: backend/apps/devices/urls.py
- modified: backend/apps/encryption/registry.py
- modified: backend/apps/makerspaces/module_purge_collectors_devices.py
- modified: backend/apps/makerspaces/module_purge_plans.py
- modified: backend/apps/makerspaces/origin_scope_model_lookups.py
- modified: backend/apps/makerspaces/origin_scope_routes.py
- modified: backend/apps/tenant_migration/audit_references_meta_devices.py
- modified: backend/apps/tenant_migration/omitted_fields.py
- modified: backend/apps/tenant_migration/references_devices.py
- modified: backend/apps/tenant_migration/row_planning.py
- modified: backend/apps/tenant_migration/target_projection.py
- modified: backend/apps/tenant_migration/tenant_dump_authority_devices.py
- modified: backend/apps/tenant_migration/tenant_dump_catalog.py
- modified: backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- modified: backend/apps/tenant_migration/tenant_dump_model_catalog.py
- modified: backend/apps/tenant_migration/tenant_dump_raw.py
- modified: backend/apps/tenant_migration/unique_values.py
- modified: backend/config/settings.py
- modified: backend/tests/encryption/test_mappers.py
- modified: backend/tests/tenant_migration/test_authority_dispositions_d8.py
- modified: docs/INVARIANTS.md
- modified: docs/MODULES.md
- modified: docs/SOURCE-MAP.md
- modified: docs/deploy-production.md
- modified: docs/self-hosting.md
- created: backend/apps/data_export/classification_7b.py
- created: backend/apps/data_export/credentials_7b.py
- created: backend/apps/data_export/datasets_7b.py
- created: backend/apps/data_export/guards_credentials.py
- created: backend/apps/data_export/references_7b.py
- created: backend/apps/devices/admin_printers.py
- created: backend/apps/devices/errors_printers.py
- created: backend/apps/devices/migrations/0002_printer_jobs.py
- created: backend/apps/devices/migrations/_printer_claim_guards.py
- created: backend/apps/devices/models_commands.py
- created: backend/apps/devices/models_printers.py
- created: backend/apps/devices/printer_access.py
- created: backend/apps/devices/printer_state.py
- created: backend/apps/devices/route_registry_7b.py
- created: backend/apps/devices/serializers_commands.py
- created: backend/apps/devices/serializers_printers.py
- created: backend/apps/devices/services_commands.py
- created: backend/apps/devices/services_printer_apply.py
- created: backend/apps/devices/services_printer_bindings.py
- created: backend/apps/devices/services_printer_events.py
- created: backend/apps/devices/services_printer_jobs.py
- created: backend/apps/devices/services_printer_reports.py
- created: backend/apps/devices/urls_7b.py
- created: backend/apps/devices/views_commands.py
- created: backend/apps/devices/views_printer_common.py
- created: backend/apps/devices/views_printer_protocol.py
- created: backend/apps/devices/views_printers.py
- created: backend/apps/encryption/registry_7b.py
- created: backend/apps/makerspaces/module_purge_collectors_7b.py
- created: backend/apps/makerspaces/origin_scope_routes_7b.py
- created: backend/apps/tenant_migration/audit_references_meta_7b.py
- created: backend/apps/tenant_migration/catalog_7b.py
- created: backend/apps/tenant_migration/references_7b.py
- created: backend/apps/tenant_migration/target_projection_7b.py
- created: backend/apps/tenant_migration/tenant_dump_authority_7b.py
- created: backend/apps/tenant_migration/unique_values_7b.py
- created: backend/tests/devices/printer_helpers.py
- created: backend/tests/devices/test_command_leases.py
- created: backend/tests/devices/test_printer_bindings.py
- created: backend/tests/devices/test_printer_boundaries.py
- created: backend/tests/devices/test_printer_data_export.py
- created: backend/tests/devices/test_printer_dump_projection.py
- created: backend/tests/devices/test_printer_jobs.py
- created: backend/tests/devices/test_printer_reconciliation.py
- created: backend/tests/devices/test_printer_results.py
- created: backend/tests/devices/test_printer_settings.py
- created: backend/tests/devices/test_printer_state.py
- created: backend/tests/devices/test_printer_tenant_migration.py
- created: backend/tests/tenant_migration/authority_expectations_7b.py
- created: backend/tests/tombstone/test_printer_devices_7b.py
- created: docs/device-printer-protocol.md
- created: stage1-p7b.md

## Every new test function

### backend/tests/devices/test_command_leases.py

- test_lease_returns_token_once_stores_digest_and_acks_after_long_print
- test_expired_ack_commits_requeue_backoff_and_old_token_cannot_ack_new_lease
- test_final_expired_attempt_marks_delivery_failed
- test_cross_device_and_revoked_principals_cannot_claim_or_ack
- test_adapter_off_or_missing_target_cancels_delivery_permanently
- test_rotation_does_not_transfer_command_to_new_key
- test_two_pollers_lease_one_command_exactly_once

### backend/tests/devices/test_printer_bindings.py

- test_bindings_default_to_manual_review_and_reject_cross_tenant_wrong_kind
- test_manage_devices_alone_never_widens_machine_scope
- test_disabling_or_deleting_binding_cancels_acknowledged_work_and_preserves_history
- test_binding_service_denies_missing_device_authority
- test_explicit_unbind_retires_inert_imported_review_without_workflow_effect

### backend/tests/devices/test_printer_boundaries.py

- test_applied_marker_or_provenance_failure_rolls_back_stock_money_and_workflow
- test_claim_provenance_failure_rolls_back_whole_claim
- test_wrong_machine_duplicate_and_fractional_count_consumptions_are_rejected
- test_canonical_consumption_order_replays_and_operation_id_cannot_bind_another_job
- test_staff_approval_rechecks_machine_scope_and_device_kind_is_checked_per_report

### backend/tests/devices/test_printer_data_export.py

- test_printer_models_fields_user_edges_and_no_lease_credentials_are_exported
- test_failure_note_is_encrypted_and_not_copied_into_audit
- test_device_purge_removes_all_printer_rows_and_retains_machine_workflow
- test_adapter_deletion_nulls_live_links_without_erasing_printer_history
- test_mapped_report_write_is_fenced_in_service_and_raw_sql

### backend/tests/devices/test_printer_dump_projection.py

- test_raw_dump_selects_conditional_printer_job_reset

### backend/tests/devices/test_printer_jobs.py

- test_job_identity_is_explicit_unique_and_request_title_is_not_snapshotted
- test_telemetry_after_short_lease_expiry_is_advisory_and_audited_without_user_actor
- test_staff_lists_are_paginated_and_details_follow_tenant_scope
- test_adapter_module_off_is_400_and_source_gate_refuses_delivery_and_results

### backend/tests/devices/test_printer_reconciliation.py

- test_actual_weight_reconciles_reserved_pool_once
- test_reserved_pool_requires_explicit_matching_measurement
- test_same_terminal_report_from_concurrent_workers_has_one_workflow_effect
- test_failed_generic_quantity_reconciles_actual_use_without_payment

### backend/tests/devices/test_printer_results.py

- test_manual_review_is_default_and_matching_retry_and_staff_approval_apply_once
- test_auto_apply_debits_consumptions_and_authoritative_charge_exactly_once
- test_failed_result_passes_reason_percentage_and_never_creates_payment
- test_conflicting_report_payload_operation_or_external_identity_is_409
- test_invalid_or_device_pricing_input_is_rejected_before_claim
- test_workflow_failure_rolls_back_effects_keeps_claim_and_never_retries_automatically
- test_crash_between_claim_and_apply_resumes_from_durable_report
- test_report_cannot_finish_unacknowledged_or_rotated_command
- test_signed_result_api_uses_device_principal_and_keeps_actor_null
- test_claimed_report_is_immutable_in_database_including_consumption_rows

### backend/tests/devices/test_printer_settings.py

- test_command_defaults_are_declared_in_every_env_example_and_excluded_from_restore_compatibility
- test_nonpositive_command_tuning_is_rejected_by_system_checks

### backend/tests/devices/test_printer_state.py

- test_effective_printer_state_precedence
- test_old_or_terminal_telemetry_never_overrides_idle

### backend/tests/devices/test_printer_tenant_migration.py

- test_printer_catalog_projection_references_and_uniqueness_are_complete
- test_conditional_field_projection_inerts_unprocessed_work_and_preserves_history
- test_portable_printer_history_imports_with_no_remote_authority_and_no_workflow_replay

### backend/tests/tombstone/test_printer_devices_7b.py

- test_printer_routes_are_absent_when_devices_are_tombstoned
- test_printer_admin_and_schema_are_absent_but_tables_remain

Existing test files modified: backend/tests/encryption/test_mappers.py updates the deliberate source/total PII counts and explanation; backend/tests/tenant_migration/test_authority_dispositions_d8.py includes the independent nine-entry authority fixture. Helpers/fixtures added: printer_helpers.py and authority_expectations_7b.py.
