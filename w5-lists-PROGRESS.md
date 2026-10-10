# w5-lists handoff

Implementation complete; all changes remain unstaged in this worktree. No state-changing git commands, database tests, generated API regeneration, merges, commits, or pushes were performed.

## Completed

- URL source-of-truth filters, sort, and page across requests (four independent queues), inventory, members (roster/join requests), payments, bookings (space list and namespaced booking drawer), events, and audit. Back/Forward restores state; filter changes reset pages.
- Controlled table sorting requests server ordering rather than rearranging a single page. Stable allowlisted ordering appends the primary key to avoid tied rows moving between pages.
- Staff payment reconciliation now returns the standard paginated response, default 24; receipt/label enrichment is limited to the page. Inventory no longer fetches 1,000 rows for its staff list. Other named lists use server pagination with a default of 24.
- SavedView model: per-user/private by default; makerspace sharing requires MANAGE_MAKERSPACE. Reading a shared preference never grants entity permission; only its owner edits/deletes. All mutations are atomic and audited, with explicit share/unshare events.
- GET /api/v1/admin/search: required makerspace_id; q length 2..100; limit 1..10/default 5 per entity; 60/minute user throttle; typed minimal hits across requests/inventory/members/bookings/events/machines. Action scope, machine role scope, disabled modules, tenant browser origin and encrypted request indexes are respected.
- Ctrl/Cmd+K command palette: permitted navigation plus debounced scoped search, ARIA combobox/listbox, arrows/Home/End/Enter/Escape, active-result scrolling, focus restoration, loading/error/empty states. Booking/event/machine hits open their scoped drawers; booking IDs filter on the server even beyond page 1.
- Saved-view menu: save/apply/delete, manager sharing, paginated views, errors and cache invalidation. Cache keys include username, makerspace and entity.
- SavedView export classification, dataset, User FK closure, inert-JSON declaration, catalog fields, authority reset and target import projection. Import resets shared/state to prevent source publication/filter IDs becoming target authority.
- Booking-space/event handlers split behind explicit re-export barrels; source-map frontend details moved to a sibling to obey the file ceiling.
- drf-spectacular definitions updated for new routes, filters, ordering, pagination and errors. Generated schema/client deliberately untouched.

## Previous implementation checks (historical)

- Final focused Vitest run: 9 suites, 54 tests passed (URL state, command palette, saved menu, DataTable, payments, offline refunds, members, audit, machines).
- Final npx.cmd tsc --noEmit: exit 0.
- Python AST parsing for every changed/new Python file: valid.
- Every touched file is at most 300 lines; git diff --check clean; AGENTS.md and CLAUDE.md unchanged and byte-identical; index empty.
- Backend tests were WRITTEN but NOT RUN. Django/Docker/Postgres are unavailable to this lane. No backend correctness or migration execution is claimed.

## Migration

backend/apps/operations/migrations/0011_saved_view.py
Dependencies: operations.0009_report_schedules (confirmed actual pre-change leaf), migrations.swappable_dependency(settings.AUTH_USER_MODEL). Makerspace schema dependency is inherited through 0009.

## Coordinator work remaining

1. Review the unstaged lane. Preserve split-first commit ordering for booking-space/event handler files; this lane cannot commit.
2. Run ./scripts/dev.sh test for the four operations test files listed below, and changed receipt/reconciliation/loan/terminal-payment tests.
3. Run data-export registry guards, tenant-dump catalog/authority/projection guards, audit presentation guards, origin-scope and module registry guards. Catalog hash was derived offline from snapshots after reproducing the exact baseline hash; validate/recompute against the live MERGED Django graph before committing.
4. Run migration drift check (makemigrations --check), generate OpenAPI schema and TypeScript client in the integration lane, then frontend checks against regenerated artifacts.
5. Run formal Codex review/QA and browser QA. codex doctor here reported missing configuration/home and unreachable provider; that gate was unavailable, not passed.

Suggested backend targets: tests/operations/test_saved_view_portability.py tests/operations/test_saved_views.py tests/operations/test_staff_search.py tests/operations/test_staff_list_pagination.py tests/payments/test_reconciliation.py tests/payments/test_receipt_visibility.py tests/hardware_requests/test_loan_payments.py tests/tenant_migration/test_terminal_payments_d8.py tests/data_export/test_registry_guards.py tests/tenant_migration/test_tenant_dump_catalog_d1.py tests/tenant_migration/test_projected_catalog_travel_guard.py tests/tenant_migration/test_authority_guard.py tests/test_audit_presentation.py tests/makerspaces/test_origin_scope_p2b.py tests/tenant_migration/test_reference_registry.py tests/tenant_migration/test_source_gate_guards.py tests/data_export/test_portable_audit_references.py

## Defaults, omissions and owner decisions

Per-user saved views and MANAGE_MAKERSPACE-only sharing follow the stated owner default. No new module/feature keys were introduced for these core console ergonomics. No blocking product decisions remain. Members match existing usernames; bookings match space name/booking ID. Broader personal-name/email fuzzy discovery is deferred because it requires an indexing/privacy definition absent from the plan default. Research-only bulk actions, quick-create commands, density/column customization and unrelated lists are outside the explicit lane build.

Backend execution, OpenAPI regeneration and formal review are deferred solely to the coordinator/environment, not omitted implementation.

## Outside-task defect noticed

Existing shared Modal can miss initial focus when mounted closed and then opened: top === tokenRef.current is initially true when both are null, so the later [amTop] focus effect can miss the transition. New palette/save dialogs mount only while open and their focus behavior is tested. Shared Modal itself was not changed.

## New backend test functions (not run)

backend/tests/operations/test_saved_views.py
- test_private_views_follow_owner_and_refuse_other_tenants
- test_only_managers_share_and_peers_cannot_change_shared_views
- test_shared_view_never_grants_access_to_an_entity_and_module_off_is_400
- test_saved_state_is_bounded_and_inert
- test_deleted_view_is_audited_and_list_is_paginated
- test_import_projection_clears_source_publication_and_identity_filters

backend/tests/operations/test_staff_list_pagination.py
- test_inventory_sorts_the_whole_scoped_queryset_before_paging
- test_payment_list_is_bounded_and_orders_before_paging

backend/tests/operations/test_staff_search.py
- test_search_is_tenant_scoped_and_returns_only_typed_minimal_hits
- test_inventory_only_staff_cannot_discover_members_requests_or_events
- test_handover_staff_never_see_pending_or_draft_requests
- test_search_limits_each_entity_and_omits_disabled_modules
- test_search_validates_inputs
- test_search_is_throttled
- test_large_numeric_search_cannot_overflow_booking_primary_keys
- test_suspended_actor_cannot_search_or_access_saved_views
- test_machine_search_obeys_role_machine_scope
- test_tenant_browser_origin_cannot_search_a_second_authorized_tenant
- test_encrypted_search_candidates_are_intersected_with_request_scope

## New frontend test coverage

- frontend/src/lib/useUrlListState.test.tsx: encoded round-trip/back-forward/saved restore; invalid pages; reset all queue pages; drawer/parent namespace independence.
- frontend/src/features/staff/CommandPalette.test.tsx: keyboard open/movement/selection/Escape/focus restoration plus axe; selected-tenant search/results/navigation permissions; errors/empty results retain keyboard operation.
- frontend/src/features/staff/SavedViewsMenu.test.tsx: personal save/server restore; manager publication.
- frontend/src/components/ui/DataTable.test.tsx: server-page ordering and sort callback; legacy local sorting.

## Existing test adaptations

- backend/tests/hardware_requests/test_loan_payments.py, backend/tests/payments/test_reconciliation.py, backend/tests/payments/test_receipt_visibility.py, backend/tests/tenant_migration/test_terminal_payments_d8.py: standard paginated payment response.
- frontend/src/features/staff/MembersPanel.test.tsx, frontend/src/features/staff/PaymentsPanel.test.tsx, frontend/src/features/staff/PaymentOfflineRefund.test.tsx, frontend/src/features/staff/panels/AuditLog.test.tsx: router context, URL query state, saved-view queries and paginated payment mock data.

## Review pass

Completed 2026-10-11. Read root instructions, the main-checkout research brief, the existing handoff,
the tracked diff and all new implementation/test files. The requested w5-lists-PROGRESS.md was missing;
it is now a current copy of this handoff. All edits remain inside this worktree and unstaged.

Defects found and fixed:

1. Request queues and the membership-request list relied on tenant permission checks without scoping
   their row querysets through RBAC. Added explicit action scopes; also scoped the roster waiver query.
2. Membership-request state/sort had no URL controls or query-key inputs. Added independent request
   state/sort, encoded API parameters, page reset and saved-state support; the roster page stays intact.
3. Invalid event/member/request-state enums silently produced empty lists. Added boundary validation
   returning 400, so a malformed bookmark is reported as an invalid filter.
4. Inventory/member/request palette hits reapplied only a term; the selected row could be on another
   page. Added bounded optional ID filters AFTER tenant/action scoping, typed search navigation IDs,
   query-key inputs and a clear-selection control. Exact selection never widens a tenant or queue.
5. Saved-view audit targets were live REMAP references despite preferences being deletable. Declared
   typed inert source provenance for saved-view targets, preserving durable audit evidence without
   requiring a deleted row to exist during portable import. Added actual portable archive coverage.
6. Deleting the last saved view on page two could strand the menu on an invalid page. Successful
   management mutations now return to page one while invalidating the user's scoped view cache.
7. Split booking/event detail routes omitted authentication/module-off errors in OpenAPI; saved-view
   methods omitted explicit bodyless requests and source-freeze errors. Completed those declarations,
   retained explicit barrel exports, and documented the new identity-filter parameter.
8. Payment BULK-action test wrongly expected the paginated LIST envelope. Restored its array assertion.
   The event-handler split also changed the existing registration maximum from 500 to 240; restored 500.
9. Lane files contained CRLF and stray byte-order marks, including an embedded BOM before an import.
   Normalized every touched text file to UTF-8/LF, removed BOMs and checked for mojibake.

Latest verification:

- python -m py_compile: all 44 touched Python files compiled; no backend tests were executed.
- frontend/npx.cmd tsc -b: exit 0.
- frontend/npx.cmd vitest run src/lib/useUrlListState.test.tsx src/components/ui/DataTable.test.tsx
  src/features/staff: 71 suites, 298 tests passed. Existing jsdom document-navigation diagnostic is non-failing.
- git diff --check clean; index empty; all touched files <=300 lines; AGENTS.md/CLAUDE.md remain byte-identical.
- No new environment variables, tasks, fan-outs or object writers were introduced. Source-gate HTTP
  participation uses the default guarded JWT authenticator and makerspace-bearing routes; a freeze test
  covers POST/PATCH/DELETE. No gate_policy task/object additions or environment-reference edits are needed.
- SavedView model/FK/export/catalog/authority/target projections and actual migration leaf were reviewed.
  The catalog pin still requires validation against the coordinator's live merged Django model graph.
- codex doctor still fails configuration/home and provider reachability. External CLI review and browser
  QA are coordinator work; this review does not claim those gates passed.

Additional backend tests written in this review (NOT RUN):

- tests/operations/test_saved_view_portability.py:
  test_deleted_and_live_saved_views_keep_inert_audit_targets_in_portable_export;
  test_import_planner_resets_publication_and_source_filters_on_saved_view_rows.
- tests/operations/test_saved_views.py:
  test_updates_preserve_ownership_and_audit_without_copying_private_filters;
  test_former_manager_must_unshare_before_editing_a_published_view;
  test_source_freeze_blocks_saved_view_writes_but_leaves_reads_available.
- tests/operations/test_staff_list_pagination.py:
  test_request_queue_sorts_ties_stably_and_refuses_other_tenants;
  test_member_roster_filters_and_sorts_before_paginating;
  test_membership_request_list_scopes_filters_and_orders_server_side;
  test_bookable_spaces_and_booking_id_filter_work_beyond_page_one;
  test_event_list_filters_sorts_and_paginates_within_its_tenant;
  test_audit_ordering_remains_stable_and_tenant_scoped_across_pages.
  Extended the original inventory/request/member pagination tests with bounded ID/cross-scope checks.
- tests/operations/test_staff_search.py:
  test_organization_action_grants_reach_search_without_widening_entity_authority;
  test_hidden_and_archived_tenants_are_refused_even_for_a_global_superadmin;
  test_search_does_not_discover_an_entity_when_its_module_is_off (three parameter cases).
  Extended typed-hit coverage to assert exact navigation IDs.

Additional frontend tests: SavedViewsMenu.test.tsx deletes the final view on a later page;
MembersPanel.test.tsx exercises independent request state/sort and clearing an exact palette selection;
CommandPalette.test.tsx now verifies exact typed-result navigation.

No additional migration was needed. No blocking owner decisions remain. The original omissions and
outside-task Modal focus defect above still apply. Backend execution, schema generation, live catalog
verification and browser QA remain explicitly deferred to the coordinator.

## Complete file manifest

- LANE-PROGRESS.md (new)
- backend/apps/admin_api/list_options.py (new)
- backend/apps/admin_api/search.py (new)
- backend/apps/admin_api/serializers_member_list.py (new)
- backend/apps/admin_api/staff_list_scope.py (new)
- backend/apps/admin_api/views_inventory_products.py
- backend/apps/admin_api/views_member_memberships.py
- backend/apps/admin_api/views_users.py
- backend/apps/audit/presentation_catalog_platform.py
- backend/apps/bookings/serializers_admin.py
- backend/apps/bookings/views_admin_bookings.py
- backend/apps/bookings/views_admin_space_detail.py (new)
- backend/apps/bookings/views_admin_space_list.py (new)
- backend/apps/bookings/views_admin_spaces.py
- backend/apps/data_export/classification_domain.py
- backend/apps/data_export/datasets.py
- backend/apps/data_export/guards.py
- backend/apps/data_export/references_core.py
- backend/apps/events/views_admin_event_detail.py (new)
- backend/apps/events/views_admin_event_list.py (new)
- backend/apps/events/views_admin_events.py
- backend/apps/hardware_requests/queue_views.py
- backend/apps/makerspaces/origin_scope_routes.py
- backend/apps/operations/migrations/0011_saved_view.py (new)
- backend/apps/operations/models.py
- backend/apps/operations/models_saved_views.py (new)
- backend/apps/operations/serializers_saved_views.py (new)
- backend/apps/operations/urls.py
- backend/apps/operations/views_saved_views.py (new)
- backend/apps/payments/serializers_reconciliation.py
- backend/apps/payments/views_reconciliation.py
- backend/apps/tenant_migration/audit_references_targets.py
- backend/apps/tenant_migration/target_projection.py
- backend/apps/tenant_migration/tenant_dump_authority_supplement.py
- backend/apps/tenant_migration/tenant_dump_catalog.py
- backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- backend/apps/tenant_migration/tenant_dump_model_catalog.py
- backend/tests/hardware_requests/test_loan_payments.py
- backend/tests/operations/test_saved_view_portability.py (new)
- backend/tests/operations/test_saved_views.py (new)
- backend/tests/operations/test_staff_list_pagination.py (new)
- backend/tests/operations/test_staff_search.py (new)
- backend/tests/payments/test_receipt_visibility.py
- backend/tests/payments/test_reconciliation.py
- backend/tests/tenant_migration/test_terminal_payments_d8.py
- docs/SOURCE-MAP-CONSOLES.md (new)
- docs/SOURCE-MAP.md
- frontend/src/components/ui/DataTable.test.tsx (new)
- frontend/src/components/ui/DataTable.tsx
- frontend/src/features/staff/BookingDrawer.tsx
- frontend/src/features/staff/BookingsPanel.tsx
- frontend/src/features/staff/CommandPalette.test.tsx (new)
- frontend/src/features/staff/CommandPalette.tsx (new)
- frontend/src/features/staff/EventsPanel.tsx
- frontend/src/features/staff/ListViewControls.tsx (new)
- frontend/src/features/staff/MembersPanel.test.tsx
- frontend/src/features/staff/MembersPanel.tsx
- frontend/src/features/staff/PaymentOfflineRefund.test.tsx
- frontend/src/features/staff/PaymentsPanel.test.tsx
- frontend/src/features/staff/PaymentsPanel.tsx
- frontend/src/features/staff/SavedViewsMenu.test.tsx (new)
- frontend/src/features/staff/SavedViewsMenu.tsx (new)
- frontend/src/features/staff/StaffListContext.tsx (new)
- frontend/src/features/staff/StaffTabContent.tsx
- frontend/src/features/staff/StaffWorkspace.tsx
- frontend/src/features/staff/bookingsApi.ts
- frontend/src/features/staff/eventsApi.ts
- frontend/src/features/staff/panels/AuditLog.test.tsx
- frontend/src/features/staff/panels/AuditLog.tsx
- frontend/src/features/staff/panels/AuditLogFilters.tsx
- frontend/src/features/staff/panels/Inventory.tsx
- frontend/src/features/staff/panels/MachinesPanel.tsx
- frontend/src/features/staff/panels/Queues.tsx
- frontend/src/lib/usePaginatedQuery.ts
- frontend/src/lib/useUrlListState.test.tsx (new)
- frontend/src/lib/useUrlListState.ts (new)
- w5-lists-PROGRESS.md (new)
