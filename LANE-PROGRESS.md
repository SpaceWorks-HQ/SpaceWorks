# w7-inventory - WP4 items 21-26

Completed implementation; all changes are unstaged. No git state-changing commands used.
All writes are within this worktree. No database suite was run.

## Completed

- 21: derived public loan/deposit terms and editable public terms; own-account one-shot notify-me through availability and F1, with audit and private recipient delivery.
- 22: scheduled stocktakes, policy snapshots, blind responses, absolute per-line variance thresholds, independent manager approval and auto-approval within threshold. Invalid count targets/containers now fail with validation errors instead of server errors.
- 23: independent public machine detail/collection, database-maintained status-since, opted-in training disclosure and aggregate queue ETA. machines/views_public.py remains untouched.
- 24: days/usage/both maintenance, ledger/service-derived hours/jobs, server completion baseline, retained recurrence anchors and separate F1 meter occurrences.
- 25: local material/colour catalogues, protected printer defaults, validated custom version-1 intake and public/member submission controls.
- 26: hashed staff maintenance ICS, current machine scope, rotation/revocation, stable UID/ETag, bearer-path log suppression.
- Seven opt-in feature keys in a WP4 sibling; no module keys. Export/reference/catalog/projection/purge and API-client/origin coverage added.
- Public inventory tests split into explicit-import siblings; all 26 original test functions preserved and borrowing_terms added to the allowlist.

## Validation completed here

- Focused React suite: 4 files, 27 tests passed (NotifyWhenBack, MachineIntakeForm, PublicPrintRequestForm, MachinesPanel).
- TypeScript no-emit completed: errors only in the five owner-identified pre-existing files; no WP4 errors.
- Changed Python files parsed with ast; every touched file is <=300 lines.
- git diff --check passed. AGENTS.md and CLAUDE.md remain byte-identical and unchanged.
- Forbidden machines/views_public.py and frontend generated schema/types remain unchanged.
- Focused Vitest uses frontend/wp4.vitest.config.mjs to keep Vite cache within the lane. Dependencies were read through an ignored node_modules junction to the main checkout.

## Remaining coordinator work

- Run the isolated database suite; backend tests below are written, NOT run or claimed passing.
- Run migration drift/system/OpenAPI/export/tenant-authority/projection/origin/API-client guards with Django/Postgres.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts after all lanes are combined.
- Repin the merged tenant catalog schema digest; this lane intentionally does not repin the integration-wide hash.
- Reconcile other-lane edits to shared registry barrels, events middleware and nginx bearer-feed logging.
- Mandatory nested Codex CLI gates could not run: doctor reported unresolved config/home and provider reachability failures. Coordinator must complete review/QA.
- Suggested backend command: ./scripts/dev.sh test tests/test_inventory_notify_me.py tests/test_public_inventory.py tests/operations tests/machines tests/maintenance tests/test_wp4_contracts.py tests/data_export tests/tenant_migration
- Frontend command: node node_modules/vitest/vitest.mjs run src/features/inventory/NotifyWhenBack.test.tsx src/features/inventory/MachineIntakeForm.test.tsx src/features/printing/PublicPrintRequestForm.test.tsx src/features/staff/panels/MachinesPanel.test.tsx --config wp4.vitest.config.mjs --configLoader runner --maxWorkers 1
- TypeScript command from root: node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json --noEmit --incremental false --pretty false

## Migrations and dependencies

- inventory/0014_public_terms_and_watch.py: inventory/0013_product_master_data; swappable accounts.User.
- operations/0013_stocktake_discipline.py: operations/0012_report_schedule_rules.
- machines/0026_public_detail_materials_intake.py: machines/0025_machine_type_policy.
- maintenance/0003_meters_and_feed.py: maintenance/0002_schedule_anchor; machines/0026_public_detail_materials_intake; swappable accounts.User.
- Actual leaves were listed before creation. Migration execution and reversal need coordinator validation.

## Skipped / owner decisions / outside defects

- No additional owner decision is needed for WP4. Existing defaults apply; new features are opt-in, null variance threshold preserves mandatory approval, unconfigured material catalogues inherit the global pack.
- Deferred reservations, new request states, induction mechanics, work orders, lockout and material pricing were not built. Owner-approved events/bookings membership independence and the loans master switch belong to other lanes.
- Existing machines/views_public.py exposes search matches over location, firmware and private notes, and returns 404 when its module is off. WP2 owns this file; coordinator should resolve there.
- Known TypeScript defects remain in generated/api.ts, members/MemberPayments.test.tsx, staff/MembersPanel.tsx, staff/PaymentBilling.test.tsx and staff/panels/OrganizedEventsPanel.test.tsx.

## Added backend tests (coordinator must run)

- backend/tests/machines/test_material_catalogue.py
  - test_local_materials_do_not_edit_global_pack_or_other_space
  - test_structured_intake_rejects_missing_stale_out_of_range_and_unknown
  - test_intake_accepts_valid_shape_and_rejects_reference_schema
  - test_material_write_foreign_type_refused_and_builtin_intake_protected
  - test_public_intake_never_discloses_private_or_foreign_custom_type_schema

- backend/tests/machines/test_public_machine_detail.py
  - test_allowlist_defaults_and_status_since_survives_non_status_update
  - test_queue_is_aggregate_estimate_unknown_jobs_do_not_claim_zero
  - test_module_off_400_and_private_foreign_machines_404
  - test_global_admin_hiding_does_not_hide_the_public_catalogue

- backend/tests/maintenance/test_maintenance_feed.py
  - test_hashed_rotation_revocation_and_cross_tenant_token
  - test_feed_scopes_machines_and_rechecks_revoked_operator
  - test_module_off_valid_token_400_unknown_token_404_and_stable_etag
  - test_bearer_token_is_redacted_from_access_log_sources_after_resolution
  - test_shipped_proxy_configs_suppress_bearer_feed_access_and_error_logging

- backend/tests/maintenance/test_meter_schedules.py
  - test_usage_hours_derive_from_ledger_and_reset_on_completion
  - test_job_trigger_counts_runs_and_calendar_remains_independent
  - test_threshold_validation_and_feature_off_fail_400
  - test_meter_reminder_is_tenant_scoped_and_occurrence_changes_on_completion
  - test_service_minutes_and_jobs_include_terminal_runs_without_double_counting_linked_logs

- backend/tests/operations/test_stocktake_discipline.py
  - test_blind_nested_and_count_response_hide_expected_and_variance
  - test_large_variance_needs_different_approver_and_low_variance_autoapproves
  - test_scheduled_count_skips_missed_intervals_and_dispatch_is_idempotent
  - test_legacy_defaults_and_feature_off_remain_approval_only
  - test_schedule_api_rejects_zero_interval_foreign_container_and_unknown_fields
  - test_count_rejects_foreign_target_and_container_with_validation_errors

- backend/tests/test_inventory_notify_me.py
  - test_once_per_rise_and_own_address
  - test_terms_and_notifications_never_reveal_hidden_counts
  - test_contact_injection_cross_tenant_and_feature_off
  - test_rollback_does_not_latch_watch
  - test_terms_inherit_loan_days_and_only_show_live_deposit_policy

- backend/tests/test_wp4_contracts.py
  - test_wp4_export_projection_authority_and_schema_coverage
  - test_module_purges_delete_stocktake_preferences_and_feed_credentials_only_in_space

## Added React tests

- frontend/src/features/printing/PublicPrintRequestForm.test.tsx
  - offers only the selected material's colours and clears the old colour and spool

- frontend/src/features/inventory/MachineIntakeForm.test.tsx
  - sends versioned typed fields, with blank optional numbers omitted
  - does not render a generic job form for an absent schema

- frontend/src/features/inventory/NotifyWhenBack.test.tsx
  - subscribes the signed-in account with no contact input and cancels
  - reports an eligibility failure without showing a successful subscription

## Every created or modified file

Status: M = modified; A = new unstaged file.
- M backend/apps/accounts/rbac.py
- M backend/apps/admin_api/serializers_inventory_products.py
- M backend/apps/apiclients/scope_registry_routes.py
- M backend/apps/data_export/classification.py
- M backend/apps/data_export/datasets.py
- M backend/apps/data_export/guards.py
- M backend/apps/data_export/references_core.py
- M backend/apps/events/middleware.py
- M backend/apps/integrations/notification_catalog.py
- M backend/apps/inventory/availability_stock.py
- M backend/apps/inventory/models.py
- M backend/apps/inventory/serializers.py
- M backend/apps/inventory/urls.py
- M backend/apps/machines/models.py
- M backend/apps/machines/models_catalog.py
- M backend/apps/machines/printer_capabilities.py
- M backend/apps/machines/public_printer_service.py
- M backend/apps/machines/public_printer_service_serializers.py
- M backend/apps/machines/serializers_machines.py
- M backend/apps/machines/service_workflow_actions.py
- M backend/apps/machines/service_workflow_helpers.py
- M backend/apps/machines/urls.py
- M backend/apps/maintenance/models.py
- M backend/apps/maintenance/notifications.py
- M backend/apps/maintenance/reminders.py
- M backend/apps/maintenance/serializers.py
- M backend/apps/maintenance/services_workflows.py
- M backend/apps/maintenance/urls.py
- M backend/apps/maintenance/views_overdue.py
- M backend/apps/makerspaces/capability_definitions.py
- M backend/apps/makerspaces/loan_policy.py
- M backend/apps/makerspaces/module_purge_collectors.py
- M backend/apps/makerspaces/module_purge_collectors_single_model.py
- M backend/apps/makerspaces/origin_scope_routes.py
- M backend/apps/operations/models.py
- M backend/apps/operations/reminder_registry.py
- M backend/apps/operations/serializers.py
- M backend/apps/operations/services_stocktake_workflow.py
- M backend/apps/operations/urls.py
- M backend/apps/operations/views_stocktake.py
- M backend/apps/tenant_migration/audit_references_targets.py
- M backend/apps/tenant_migration/authority_guards.py
- M backend/apps/tenant_migration/target_projection_fields.py
- M backend/apps/tenant_migration/target_projection_references.py
- M backend/apps/tenant_migration/target_projection_rows.py
- M backend/apps/tenant_migration/tenant_dump_authority.py
- M backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- M backend/apps/tenant_migration/tenant_dump_model_catalog.py
- M backend/tests/test_public_inventory.py
- M docker/allinone/nginx.conf
- M frontend/nginx.conf
- M frontend/src/features/inventory/PublicItemPage.tsx
- M frontend/src/features/inventory/PublicMachinesPage.tsx
- M frontend/src/features/printing/PublicPrintRequestForm.test.tsx
- M frontend/src/features/printing/PublicPrintRequestForm.tsx
- M frontend/src/features/printing/PublicPrintRequestPage.tsx
- M frontend/src/features/printing/publicApi.ts
- M frontend/src/features/staff/StaffTabContent.tsx
- M frontend/src/features/staff/machinesApi/types.ts
- M frontend/src/features/staff/panels/InventoryPanelParts.tsx
- M frontend/src/features/staff/panels/InventoryPanelShared.ts
- M frontend/src/features/staff/panels/MachinesPanel.tsx
- M frontend/src/features/staff/panels/StocktakeCountSection.tsx
- M frontend/src/features/staff/panels/StocktakeSessionPanel.tsx
- M frontend/src/features/staff/panels/machine/MachineDrawer.tsx
- M frontend/src/features/staff/panels/machine/MachineTypePage.tsx
- M frontend/src/features/staff/panels/machine/MaintenanceSchedules.tsx
- M frontend/src/features/staff/panels/machine/MaintenanceTab.tsx
- M frontend/src/features/staff/panels/machine/OverviewTab.tsx
- M frontend/src/features/staff/panels/machine/maintenanceApi.ts
- M frontend/src/lib/features.ts
- M frontend/src/types/inventory.ts
- A LANE-PROGRESS.md
- A backend/apps/accounts/rbac_catalogue.py
- A backend/apps/apiclients/scope_registry_wp4.py
- A backend/apps/data_export/classification_wp4.py
- A backend/apps/data_export/datasets_wp4.py
- A backend/apps/inventory/migrations/0014_public_terms_and_watch.py
- A backend/apps/inventory/models_watch.py
- A backend/apps/inventory/notify_me.py
- A backend/apps/inventory/public_terms.py
- A backend/apps/inventory/views_watch.py
- A backend/apps/machines/intake.py
- A backend/apps/machines/material_catalogue.py
- A backend/apps/machines/migrations/0026_public_detail_materials_intake.py
- A backend/apps/machines/models_materials.py
- A backend/apps/machines/public_detail.py
- A backend/apps/machines/public_detail_validation.py
- A backend/apps/machines/serializers_public_detail.py
- A backend/apps/machines/views_intake.py
- A backend/apps/machines/views_materials.py
- A backend/apps/machines/views_public_detail.py
- A backend/apps/maintenance/calendar_feed.py
- A backend/apps/maintenance/meter_jobs.py
- A backend/apps/maintenance/meters.py
- A backend/apps/maintenance/migrations/0003_meters_and_feed.py
- A backend/apps/maintenance/models_feed.py
- A backend/apps/maintenance/reminders_meters.py
- A backend/apps/maintenance/views_feed.py
- A backend/apps/makerspaces/capability_definitions_wp4.py
- A backend/apps/makerspaces/origin_scope_routes_wp4.py
- A backend/apps/operations/migrations/0013_stocktake_discipline.py
- A backend/apps/operations/models_stocktake_discipline.py
- A backend/apps/operations/serializers_stocktake.py
- A backend/apps/operations/stocktake_discipline.py
- A backend/apps/operations/views_stocktake_discipline.py
- A backend/apps/tenant_migration/authority_wp4.py
- A backend/apps/tenant_migration/catalog_wp4.py
- A backend/apps/tenant_migration/projection_wp4.py
- A backend/tests/machines/test_material_catalogue.py
- A backend/tests/machines/test_public_machine_detail.py
- A backend/tests/maintenance/test_maintenance_feed.py
- A backend/tests/maintenance/test_meter_schedules.py
- A backend/tests/operations/test_stocktake_discipline.py
- A backend/tests/public_inventory_cases_1.py
- A backend/tests/public_inventory_cases_2.py
- A backend/tests/public_inventory_cases_3.py
- A backend/tests/public_inventory_helpers.py
- A backend/tests/test_inventory_notify_me.py
- A backend/tests/test_wp4_contracts.py
- A docs/WP4-INVENTORY.md
- A frontend/src/features/inventory/MachineIntakeForm.test.tsx
- A frontend/src/features/inventory/MachineIntakeForm.tsx
- A frontend/src/features/inventory/NotifyWhenBack.test.tsx
- A frontend/src/features/inventory/NotifyWhenBack.tsx
- A frontend/src/features/staff/panels/StocktakeDiscipline.tsx
- A frontend/src/features/staff/panels/machine/MaintenanceFeedControl.tsx
- A frontend/src/features/staff/panels/machine/MaintenanceMeterFields.tsx
- A frontend/src/features/staff/panels/machine/MaterialCataloguePanel.tsx
- A frontend/src/features/staff/panels/machine/PublicMachineDisclosure.tsx
- A frontend/wp4.vitest.config.mjs

## Review pass

Reviewed the original brief, authoritative BUILD GAPS (including ordering and
deferrals), relevant research and repository invariants, this handoff, the tracked
diff and every new implementation/test file. All Git commands remained read-only.

Defects fixed:

1. Ineligible watches could repeatedly occupy bounded F1 discovery slots. Discovery
   now excludes terminal reminder occurrences before the limit, using a database
   timestamp representation consistently for reminder identity.
2. Stock taken before dispatch could still produce an available-again notice.
   Discovery and delivery recheck positive availability, zero stock clears pending
   readiness, and each subsequent rise has a new occurrence. Delivery-time revoked
   membership/waiver failures now produce an empty private payload.
3. Calendar-overdue `both` schedules without meter usage could crowd genuinely due
   meter schedules out of a batch. Meter thresholds now filter in SQL before the cap.
4. Stocktake locks, QR targets and container lookups bypassed the central RBAC scope;
   schedule/material FK serializer lookups also queried foreign tenant rows first.
   These reads now use scoped querysets. Bearer-feed resolution, public printer
   queries and public detail usage aggregation now use RBAC tenant boundaries too.
   The trusted internal scope supports a servable tenant ID; actor/token
   authorization remains with the caller.
5. Material/intake requests silently ignored unexpected fields. They now reject
   them. Maintenance's strict serializer now handles non-object JSON with 400.
6. Machine creation accepted `public_fields` but discarded it. The create view now
   persists the validated allowlist; invalid camera disclosure remains refused.
7. Blind stocktakes showed stored asset condition in selector labels. Blind selectors
   now omit it while normal counts retain it.
8. Public machines exposed only the first page. The page now has paging controls,
   includes page in the TanStack Query key, and constructs tenant-local page requests.
9. Selecting a print spool left required material/colour controls stale. Selection
   now synchronizes both controls to the chosen pool.
10. New mutation schemas omitted source-gate 423/503 responses, and their 400 shape
    excluded DRF field-error maps. Both error shapes are documented.
11. The portable-catalog test supplied its own current graph as the expected hash.
    It now checks actual field coverage against declarations; the independently
    pinned merged digest remains an integration check. The reminder-registry test
    now includes the new core sources and existing membership renewal, and verifies
    a tombstoned meter consumer is not eagerly imported.
12. `docs/SOURCE-MAP.md` lacked the lane's ownership map; it now links and indexes
    the WP4 modules and frontend controls. All 67 files found with CRLF were
    normalized to LF, and damaged question-mark separators were corrected.

Added regression coverage for watch starvation/rearming, meter starvation and HTTP
validation/audit, strict material/intake inputs and public workflow submission,
machine-create disclosure persistence, public pagination, blind selector labels and
spool synchronization. No new model, migration, module key, environment variable,
Celery task, deployment-wide fan-out or object writer was introduced by the review.
The new sources run within F1's existing declared source-gate participant boundary.
Migration dependencies still match the preceding actual leaves; the forbidden
`machines/views_public.py` and both generated frontend API artifacts remain unchanged.

Validation:

- Focused `npx vitest run`: 6 files, 31 tests passed (NotifyWhenBack,
  MachineIntakeForm, PublicMachinesPage, PublicPrintRequestForm, MachinesPanel,
  StocktakeCountSection).
- `npx tsc -b`: exit 2, errors only in the five owner-excluded pre-existing files;
  no lane errors. The node project's output directory was temporarily redirected
  into this worktree to avoid writing through the shared dependency junction, and
  its original config was restored byte-for-byte.
- `python -m py_compile`: all 98 touched backend Python files passed.
- `git diff --check`, LF/mojibake scans and touched application-file length checks
  passed; the index remains empty and `AGENTS.md`/`CLAUDE.md` stay byte-identical.
  The 26 extracted public-inventory tests retain their original bodies/decorators.
- No Django/database tests were run: host Python has no Django.
- `codex doctor` rechecked: config/home resolution and provider reachability fail;
  nested CLI gates remain unavailable in this sandbox.

Coordinator backend runs (from repository root, isolated runner):

```bash
./scripts/dev.sh test tests/test_inventory_notify_me.py tests/test_public_inventory.py tests/operations tests/machines tests/maintenance tests/test_wp4_contracts.py tests/data_export tests/tenant_migration tests/apiclients tests/modules tests/test_environment_reference_drift.py
```

Run the existing migration drift, source-gate, origin/API-client and schema guards;
regenerate OpenAPI/types and repin the independently reviewed catalog digest after
integration. The focused new test paths remain those listed above; registry coverage
also changes `backend/tests/operations/test_reminder_source_registry.py`.
