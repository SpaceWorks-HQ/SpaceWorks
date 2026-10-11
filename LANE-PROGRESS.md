# w4-inventory handoff

## Completed
- Bounded product/container kit definitions; physical issue and return capture on
  reviewed requests, direct handouts, member self-checkout and kiosk handover.
- Frozen issue snapshots and immutable ReturnEvent snapshots keep historic labels
  and counts after definitions change or the kit feature is disabled.
- Missing return components use existing RequesterAccountability and the existing
  closed_with_issue finalizer, without changing product loss buckets or adding charges.
  Container-only records have a nullable request_item; the timeline handles that.
- Partial returns consume only their portion of the issued component baseline.
- Manufacturer/model/SKU/barcode/supplier/reorder point/quantity staff fields and UI.
  Public inventory allowlists exclude all these fields and kit definitions.
- Availability-owned threshold observation: one F3 STOCK low_stock alert on a down
  crossing to <= the positive reorder point, no repeated alert below it, recovery
  above it rearms the next crossing. Delivery remains fail-safe and after commit.
- Tenant-scoped paginated reorder suggestions and audited, idempotent procurement
  drafts reuse active source-product drafts and honor procurement module gating.
- New and changed DTOs/routes have spectacular schemas; frontend calls are handwritten.
- Export field catalogs, non-reference JSON declarations and tenant migration
  snapshots/projection authority include the new fields. No new model/User FK.
- Explicit compatibility barrels preserve split availability/action serializer and
  capability imports; source-map recovery details were split below the file ceiling.
- Regression tests written for evidence Hard Rules, accountability, partial returns,
  crossings/rollback, tenant refusals, public privacy, procurement and physical capture.

## Verification / coordinator remaining
- Python AST parsing: no syntax findings in changed/new Python files.
- TypeScript: `node frontend/node_modules/typescript/bin/tsc -p frontend/tsconfig.json --noEmit`
  completed with exit 0. No application build or test execution was performed.
- All touched files are <=300 lines; AGENTS.md and CLAUDE.md remain byte-identical.
- Read-only `git diff --check` reported no whitespace errors.
- The implementation run did not run tests; see Review pass for subsequent frontend results.
  Django is unavailable here and Docker/Postgres are inaccessible. Backend execution remains
  the coordinator's responsibility.
- Isolated focused backend command:
  `./scripts/dev.sh test tests/test_kit_checklists.py tests/test_kit_loan_surfaces.py tests/test_kit_kiosk.py tests/test_inventory_reorder.py`
- Also run existing issue/return, direct-loan, self-checkout, kiosk/replay, procurement,
  capability/API-client-scope, data-export and tenant-migration guard suites.
- Frontend: `npm --prefix frontend test -- src/features/inventory/KitChecklist.test.tsx src/features/staff/panels/ReorderSuggestions.test.tsx src/features/kiosk/KioskOnlineHandover.test.tsx`
  plus existing kiosk online/offline suites.
- Coordinator: migration drift check / migrate, spectacular schema generation,
  generated API client and merged tenant catalog digest recomputation. Neither
  frontend generated artifact was edited; the inherited catalog digest is RECOMPUTE.
- CLI review gate unavailable: codex doctor could not resolve its home/config and
  provider in this sandbox. Coordinator must run review and required QA gates.
- All edits remain unstaged. No state-changing git commands were run.

## Defaults, skips and owner decisions
- No owner product decision required for this lane. Public Limited retains the
  existing 20% rule (the plan's conservative D8 default); reorder data is staff-only.
- Supplier is a company/name string aligned with existing procurement vendor_name.
- Kit definitions are bounded JSON on existing rows rather than a new content model;
  component UUIDs are opaque keys, never embedded foreign IDs. Existing immutable
  return events supply durable snapshots without another evidence/identity model.
- Kit feature defaults off; reorder point 0 disables alerts/suggestions. Reorder
  quantity must be positive to create a draft; no automatic purchase is made.
- Pickup windows/reservations, new request states, charging, valuation fields,
  vendor/contact models and barcode aliases are outside the requested lane.
- Offline capture can only count the loaded work package. Assign a kit container
  online and reload before going offline; unseen/current definition changes are
  refused by replay through the authoritative workflow rather than guessed locally.

## Defects noticed outside the task
- The box-checkout defect noted in the implementation handoff is fixed in Review pass.
- Adjacent fixes included: container makerspace is now read-only to prevent tenant
  reassignment; container detail reads enforce module-off 400; kiosk full-return
  payloads omit lines already fully resolved; duplicate service return item IDs refuse.

## Migrations and actual-leaf dependencies
- inventory/0013_product_master_data -> inventory/0012_loan_period_overrides.
- boxes/0011_kit_components -> boxes/0010_member_cards.
- hardware_requests/0029_kit_checklists -> hardware_requests/0028_loan_renewal_count.
- procurement/0008_reorder_source_product -> procurement/0007_tobuyitem_machine_type
  and inventory/0013_product_master_data.

## Added backend tests
- `backend/tests/test_inventory_reorder.py`:
  - `test_low_stock_crossing_alerts_once_and_recovery_rearms`
  - `test_crossing_callback_is_discarded_on_transaction_rollback`
  - `test_zero_point_disabled_and_delivery_failure_cannot_undo_quantity_change`
  - `test_direct_issue_return_and_stocktake_crossings_use_the_same_observer`
  - `test_reorder_suggestions_scoped_and_procurement_creation_audited_idempotently`
  - `test_reorder_refuses_foreign_makerspace_and_module_off`
  - `test_reorder_settings_validate_nonnegative_counts`
  - `test_public_inventory_never_exposes_private_master_or_reorder_fields`
- `backend/tests/test_kit_checklists.py`:
  - `test_issue_and_return_record_frozen_checklists`
  - `test_missing_components_create_only_new_missing_accountability`
  - `test_container_component_accountability_has_no_invented_product_line`
  - `test_partial_returns_partition_baseline_without_duplicate_accountability`
  - `test_issue_refuses_missing_unknown_duplicate_or_invalid_counts_atomically`
  - `test_checklist_never_replaces_issue_box_scan_or_photo`
  - `test_checklist_never_replaces_return_photo_or_remark`
  - `test_outstanding_kit_stays_checkable_after_feature_disabled`
  - `test_foreign_return_evidence_is_refused_with_checklist`
- `backend/tests/test_kit_kiosk.py`:
  - `test_kiosk_work_packages_and_commands_keep_counts_and_user_actor`
  - `test_replay_allows_bounded_multi_product_kits_without_widening_other_lists`
- `backend/tests/test_kit_loan_surfaces.py`:
  - `test_all_loan_surfaces_record_checklists_and_missing_component_accountability`
  - `test_staff_preview_scopes_every_reference_and_return_uses_issue_snapshot`
  - `test_member_preview_refuses_another_borrowers_loan`
  - `test_kit_definitions_are_bounded_and_validated_at_the_api_boundary`
  - `test_definition_edit_feature_off_and_foreign_product_refused`
- `backend/tests/kit_helpers.py`: shared evidence-backed loan fixtures/helpers.

## Added frontend tests
- `frontend/src/features/inventory/KitChecklist.test.tsx`:
  - requires an explicit physical count and sends 0 for a missing component.
  - does not carry counts onto another loan even with identical component keys.
  - blocks submission when the required checklist cannot be loaded.
- `frontend/src/features/kiosk/KioskOnlineHandover.test.tsx`:
  - keeps the issue blocked until counted and forwards physical counts with evidence.
- `frontend/src/features/staff/panels/ReorderSuggestions.test.tsx`:
  - creates a draft for the selected product in the selected makerspace.

## Created files
- `LANE-PROGRESS.md`
- `backend/apps/boxes/migrations/0011_kit_components.py`
- `backend/apps/hardware_requests/kit_checklists.py`
- `backend/apps/hardware_requests/kit_preview.py`
- `backend/apps/hardware_requests/kit_views.py`
- `backend/apps/hardware_requests/migrations/0029_kit_checklists.py`
- `backend/apps/hardware_requests/serializers_handover.py`
- `backend/apps/inventory/availability_stock.py`
- `backend/apps/inventory/availability_transfers.py`
- `backend/apps/inventory/kit_serializers.py`
- `backend/apps/inventory/migrations/0013_product_master_data.py`
- `backend/apps/inventory/reorder_views.py`
- `backend/apps/makerspaces/capability_definitions.py`
- `backend/apps/makerspaces/capability_validation.py`
- `backend/apps/procurement/migrations/0008_reorder_source_product.py`
- `backend/apps/procurement/services_drafts.py`
- `backend/tests/kit_helpers.py`
- `backend/tests/test_inventory_reorder.py`
- `backend/tests/test_kit_checklists.py`
- `backend/tests/test_kit_kiosk.py`
- `backend/tests/test_kit_loan_surfaces.py`
- `docs/SOURCE-MAP-RECOVERY.md`
- `frontend/src/features/inventory/KitChecklist.test.tsx`
- `frontend/src/features/inventory/KitChecklist.tsx`
- `frontend/src/features/inventory/PublicToolResultCard.tsx`
- `frontend/src/features/kiosk/KioskOnlineHandover.test.tsx`
- `frontend/src/features/staff/panels/ProductMasterFields.tsx`
- `frontend/src/features/staff/panels/ReorderSuggestions.test.tsx`
- `frontend/src/features/staff/panels/ReorderSuggestions.tsx`

## Modified files
- `backend/apps/admin_api/serializers_inventory_products.py`
- `backend/apps/admin_api/urls_inventory.py`
- `backend/apps/admin_api/views_inventory_products.py`
- `backend/apps/apiclients/scope_registry_routes.py`
- `backend/apps/audit/presentation_catalog_hardware.py`
- `backend/apps/boxes/models.py`
- `backend/apps/boxes/serializers.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/guards.py`
- `backend/apps/hardware_requests/direct_loan_returns.py`
- `backend/apps/hardware_requests/direct_loan_serializers.py`
- `backend/apps/hardware_requests/direct_loan_views.py`
- `backend/apps/hardware_requests/direct_loan_workflow.py`
- `backend/apps/hardware_requests/handover_views.py`
- `backend/apps/hardware_requests/handover_workflow.py`
- `backend/apps/hardware_requests/kiosk_online_commands.py`
- `backend/apps/hardware_requests/kiosk_serializers.py`
- `backend/apps/hardware_requests/models.py`
- `backend/apps/hardware_requests/replay_serializers.py`
- `backend/apps/hardware_requests/return_helpers.py`
- `backend/apps/hardware_requests/return_models.py`
- `backend/apps/hardware_requests/return_workflow.py`
- `backend/apps/hardware_requests/self_checkout_issue.py`
- `backend/apps/hardware_requests/self_checkout_returns.py`
- `backend/apps/hardware_requests/self_checkout_serializers.py`
- `backend/apps/hardware_requests/self_checkout_views.py`
- `backend/apps/hardware_requests/serializers.py`
- `backend/apps/hardware_requests/timeline_service_requests.py`
- `backend/apps/hardware_requests/urls.py`
- `backend/apps/integrations/lifecycle_data.py`
- `backend/apps/inventory/availability_assets.py`
- `backend/apps/inventory/availability_quantities.py`
- `backend/apps/inventory/availability_requests.py`
- `backend/apps/inventory/models.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/operations/serializers.py`
- `backend/apps/operations/views_containers.py`
- `backend/apps/procurement/models.py`
- `backend/apps/procurement/serializers.py`
- `backend/apps/procurement/services.py`
- `backend/apps/tenant_migration/tenant_dump_authority_loans.py`
- `backend/apps/tenant_migration/tenant_dump_catalog.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `docs/SOURCE-MAP.md`
- `frontend/src/features/inventory/PublicSelfCheckoutPage.tsx`
- `frontend/src/features/inventory/selfCheckoutApi.ts`
- `frontend/src/features/kiosk/KioskOfflineHandover.tsx`
- `frontend/src/features/kiosk/KioskOnlineHandover.tsx`
- `frontend/src/features/kiosk/kioskApi.ts`
- `frontend/src/features/staff/DirectLoanList.tsx`
- `frontend/src/features/staff/DirectLoanReturnModal.tsx`
- `frontend/src/features/staff/DirectLoans.tsx`
- `frontend/src/features/staff/DirectLoansTypes.ts`
- `frontend/src/features/staff/handover/IssueDialog.tsx`
- `frontend/src/features/staff/handover/ReturnDialog.tsx`
- `frontend/src/features/staff/handover/types.ts`
- `frontend/src/features/staff/panels/ContainersPanel.tsx`
- `frontend/src/features/staff/panels/Inventory.tsx`
- `frontend/src/features/staff/panels/InventoryPanelParts.tsx`
- `frontend/src/features/staff/panels/InventoryPanelShared.ts`
- `frontend/src/features/staff/panels/Queues.tsx`
- `frontend/src/features/staff/panels/QueuesAssignIssueModal.tsx`
- `frontend/src/features/staff/panels/QueuesModalTypes.ts`
- `frontend/src/features/staff/panels/QueuesReturnRequestModal.tsx`
- `frontend/src/features/staff/queryInvalidation.ts`
- `frontend/src/features/staff/useDirectLoanReturn.ts`
- `frontend/src/lib/features.ts`

## Review pass

Defects fixed:
- Copied component UUIDs, including repeated product lines, previously refused a valid
  composed kit. Collision keys now use deterministic opaque UUIDs per owner; direct
  previews and workflows agree, and return accountability stays on the correct line.
- Direct previews bypassed the self-checkout feature and selected-container module
  gates. They now return 400 under the same disabled capability conditions.
- Reorder suggestions refused inventory readers although the inventory panel is a
  read surface. VIEW_INVENTORY now permits suggestions; drafts still require EDIT_INVENTORY.
- Draft reuse could return a printing item. Reuse now requires hardware kind and
  RBAC-scoped rows; permission is checked before lookup and procurement is rechecked
  under the tenant lock before creation/reuse.
- Container PATCH allowed ancestor cycles; related parent/category/box lookups were
  unscoped. Related fields now use RBAC; container edits validate ancestry and convert
  Django model errors into typed DRF 400 responses.
- Container moves saved stale complete rows, risking overwritten kit definitions.
  Writes now lock tenant then container; PATCH writes only changed fields.
- Product/container writes could commit without their audit row. Views now keep both
  in one transaction; failure tests assert rollback. Product gates are rechecked under
  the tenant lock before the product lock, matching workflow lock order.
- ModelForms could persist invalid/raw kit JSON that API serializers rejected or
  normalized. Model validators share the serializer contract and require canonical
  keys, integer counts and the exact non-reference shape; migrations include them.
- Inventory create and changed handover routes lacked explicit auth/storage errors.
  OpenAPI annotations now include them; a real SchemaGenerator contract test was added.
- Container changes did not refresh loaded checklist previews. Their TanStack Query
  invalidation now refreshes those queries.
- Box checkout refused valid individual kits with available units outside the box.
  Its second pass is now quantity-only; the API regression checks inside/outside assets.
- The independent authority matrix omitted new lane fields and earlier-wave policies,
  and had the old membership-state disposition. Literal pins now cover the actual set.
- CRLF files, a mojibake dash and damaged source-map separators were repaired; touched
  text files are UTF-8/LF.

Verification:
- `npx.cmd tsc -b`: passed. `npx.cmd vitest run src/features/inventory src/features/staff
  src/features/kiosk`: 108 files / 428 tests passed after the frontend fix.
- `python -m py_compile`: all 71 touched backend Python files pass. Diff whitespace,
  LF, mojibake, 300-line and instruction-twin checks pass.
- A dependency-free audit confirms all 358 independent authority pins match the literal
  production overrides and dispositions; it is not a substitute for the runtime guard suites.
- AST comparison confirms moved capability-validation functions are unchanged.
- New regression files: `tests/test_w4_inventory_review.py`, `tests/test_w4_inventory_openapi.py`
  and `tests/tenant_migration/authority_expectations_research.py`; the D8 matrix test is updated.
- No new model, User relation, environment variable, task, fan-out or object writer.
  STOCK reuses F3's existing guarded delivery pipeline; current source-map entries are updated.
- No backend pytest/migration/schema generation claimed: Django is absent and Docker has
  no daemon. Generated OpenAPI/client artifacts and the inherited RECOMPUTE catalog digest
  must still be regenerated on the coordinator's complete graph. Codex doctor still cannot
  load its home/config here; the external CLI gate remains unavailable.
- Coordinator: run the four original lane test files plus `tests/test_w4_inventory_review.py`,
  `tests/test_w4_inventory_openapi.py`, `tests/tenant_migration`, `tests/data_export`,
  `tests/test_capabilities.py`, `tests/test_public_self_checkout.py`, `tests/test_procurement*.py`,
  and existing reviewed/direct/kiosk/replay regressions through the isolated dev.sh runner.
- All changes remain unstaged; only read-only git commands were used.
