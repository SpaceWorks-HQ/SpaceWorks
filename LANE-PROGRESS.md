# w7-modules handoff

Lane implementation complete for WP2 5, bookings half of 6, and 7-13. Every change
is unstaged. No Git state-changing command was run. Events implementation remains
owned by w7-events; no events application files were edited.

## Completed

- 5: maintenance dependency pin, current profile/module counts and stale docs/comment.
- 6: bookings no longer installs membership. Active accounts may book; an existing
  membership still enforces status/waiver. Own history/cancellation uses borrower RBAC
  scope instead of staff membership scope, so account-only borrowers see their own rows.
- 7: preserved independent machine_service with the global printer queue fallback test.
- 8: default-on loans.enabled sibling definition/frontend mirror and upgrade backfill.
  Off hides loan tabs/bootstrap/counters and refuses catalogue/new public borrow with
  400. Submission rechecks under the makerspace lock. Core/data stay installed;
  retained-loan policies, charge tracking and payment capabilities remain independent.
- 9: public_site_enabled separates directory/embed/machine publication from the
  inventory catalogue flag. Minimal profile disables both with an explicit audit.
  Export, saved-pack settings and portable migration field/authority entries included.
- 10: capability-based home with optional public_landing_page and automatic fallback;
  bootstrap loading cannot flash the inventory page. Lazy event detail routes in both
  single-tenant and /m/:slug forms. Minimal detail placeholder is ready for w7-events.
- 11: module/feature/action-scoped dashboard counters, event/booking queues and logged
  failures. Events staff cannot acquire hardware counts on a mixed tenant. The core
  payment ledger remains available with the online rail disabled.
- 12: low-stock procurement tenant-module gate; PartnerEvents and Presence module gates.
- 13: all five families covered on backend and frontend, including accounts without
  membership, cross-tenant refusals, retained data and paid events without an online rail.
- Split near/over-ceiling model, HMAC middleware, public request views and dashboard
  into explicit compatibility barrels plus domain siblings.

## Migration

- backend/apps/makerspaces/migrations/0086_public_site_and_loans.py
- Dependency: makerspaces.0085_space_pack_profile (actual leaf inspected).
- Adds public_site_enabled and public_landing_page. Backfills site publication from
  public_inventory_enabled and appends loans.enabled to each existing makerspace.
- No new concrete model or accounts.User FK. Field classifications/snapshot/authority
  entries live in new lane siblings. Abstract PublicSiteSettings creates no new table.

## Validation actually performed

- Focused Vitest: 10 files, 96 tests passed. New files plus existing MemberArea,
  MemberAreaPortal, MemberPortalTabs, DashboardPanel, dashboardLinks and staff-tab guards.
- tsc --noEmit: fails only in the five owner-listed pre-existing files (generated/api,
  MemberPayments.test, MembersPanel, PaymentBilling.test, OrganizedEventsPanel.test).
  No errors from lane files. No generated schema/types were changed.
- Python AST parsing succeeds for all 55 changed/new Python files. Touched source files
  are within 300 lines; AGENTS.md and CLAUDE.md remain byte-identical. git diff --check
  is clean; index empty. These are static checks, not backend test results.
- Temporary local dependency junction/test config removed after frontend validation.
- codex doctor could not resolve its configuration/reach provider; CLI review unavailable.

## Coordinator work / integration dependencies

- Run every backend test below with the isolated Docker/Postgres runner; none was run
  here. Also run affected existing suites: tests/bookings, tests/modules,
  tests/makerspaces, tests/operations dashboard, tests/capabilities_defaults.py,
  tests/test_capabilities.py, public-inventory/borrow and HMAC middleware suites,
  plus export/tenant-migration drift guards.
- Merge w7-events before the events-only contract test: registration_audience=accounts,
  events.account_registration and events independence are supplied by that lane.
- Replace frontend/src/features/inventory/PublicEventDetailPage.tsx placeholder with
  w7-events' detail implementation. Reconcile that add/add conflict, retaining this
  lane's lazy route imports.
- Run events-only tests in a real TOMBSTONED_APPS=payments_rail process as well as normal
  startup. The parameterized test also simulates both runtime manifests in-process;
  real startup verifies URL withdrawal.
- Repin CATALOG_SCHEMA_SHA256 on the merged model graph; regenerate OpenAPI/types.
- Reconcile events profile/dependency pins, docs and exact capability count/default
  assertions with w7-events' new features and removal of events -> membership.
- Complete review/QA gates and any split-only commit ordering; coordinator stages/commits.

## Skips, owner decisions and outside defects

- Events application/dependency removal, invite-only logic and real event detail page
  are intentionally left to w7-events. All deferred BUILD GAPS items are excluded.
- No guest/no-account registration, refunds-on-cancel, machine booking or other deferred
  product behavior was added. No new module keys. No further owner decisions needed.
- Existing test_event_registration_presence_p14.py still pins a presence guard import
  in bookings/views_public even though advance booking already stopped requiring
  presence before this lane. Left untouched because it belongs to events tests;
  coordinator/w7-events should update that stale assertion.
- Corrected pre-existing capabilities_defaults pins (old count/default list) and the
  missing pytest import in tests/test_capabilities.py, required for reliable collection.
- The five known TypeScript defects remain untouched for the integration fix lane.

## Complete file manifest (created or modified)

- `LANE-PROGRESS.md`
- `backend/apps/bookings/access.py`
- `backend/apps/data_export/classification_modules.py`
- `backend/apps/hardware_requests/public_request_views.py`
- `backend/apps/hardware_requests/public_status_views.py`
- `backend/apps/inventory/middleware_hmac.py`
- `backend/apps/inventory/middleware_publishable.py`
- `backend/apps/makerspaces/capability_definitions_modules.py`
- `backend/apps/makerspaces/loan_visibility.py`
- `backend/apps/makerspaces/migrations/0086_public_site_and_loans.py`
- `backend/apps/makerspaces/models_makerspace_core.py`
- `backend/apps/makerspaces/models_public_site.py`
- `backend/apps/makerspaces/public_site.py`
- `backend/apps/operations/dashboard_counts.py`
- `backend/apps/operations/dashboard_programmes.py`
- `backend/apps/operations/serializers_dashboard.py`
- `backend/apps/tenant_migration/tenant_dump_modules.py`
- `backend/tests/machines/test_low_stock_procurement_gate.py`
- `backend/tests/modules/family_helpers.py`
- `backend/tests/modules/test_family_bookings_only.py`
- `backend/tests/modules/test_family_events_only.py`
- `backend/tests/modules/test_family_features.py`
- `backend/tests/modules/test_family_inventory_only.py`
- `backend/tests/modules/test_family_machines_only.py`
- `backend/tests/modules/test_family_membership_only.py`
- `backend/tests/modules/test_machine_service_without_machines.py`
- `backend/tests/operations/test_dashboard_family_counts.py`
- `backend/tests/test_public_site_flags.py`
- `docs/SOURCE-MAP-MODULE-FAMILIES.md`
- `frontend/src/AppRoutes.familyHome.test.tsx`
- `frontend/src/features/inventory/PublicEventDetailPage.tsx`
- `frontend/src/features/members/MemberArea.moduleGates.test.tsx`
- `frontend/src/features/staff/MakerspacePublicSiteSettings.tsx`
- `frontend/src/features/staff/panels/DashboardPanel.familyOnly.test.tsx`
- `frontend/src/features/staff/staffTabs.familyOnly.test.ts`
- `frontend/src/lib/publicHome.ts`
- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/bookings/views_member.py`
- `backend/apps/bookings/views_public.py`
- `backend/apps/data_export/classification.py`
- `backend/apps/data_export/space_pack_configuration.py`
- `backend/apps/hardware_requests/public_views.py`
- `backend/apps/hardware_requests/request_workflow.py`
- `backend/apps/inventory/middleware.py`
- `backend/apps/inventory/views.py`
- `backend/apps/machines/low_stock.py`
- `backend/apps/machines/views_public.py`
- `backend/apps/makerspaces/admin.py`
- `backend/apps/makerspaces/capability_definitions.py`
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/makerspaces/module_install.py`
- `backend/apps/makerspaces/module_profiles.py`
- `backend/apps/makerspaces/module_registry_catalog.py`
- `backend/apps/makerspaces/platform.py`
- `backend/apps/makerspaces/views.py`
- `backend/apps/operations/views_dashboard_api.py`
- `backend/apps/operations/views_dashboard_counts.py`
- `backend/apps/tenant_migration/tenant_dump_authority.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/tests/capabilities_defaults.py`
- `backend/tests/makerspaces/test_module_registry.py`
- `backend/tests/modules/test_combo_profiles.py`
- `backend/tests/modules/test_offstate_facilities.py`
- `backend/tests/test_capabilities.py`
- `docs/INVARIANTS.md`
- `docs/MODULES-WORKSHOPS.md`
- `docs/MODULES.md`
- `docs/README-MODULES.md`
- `docs/SOURCE-MAP.md`
- `frontend/src/AppRoutes.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberPortalTabs.tsx`
- `frontend/src/features/staff/MakerspaceGeneralSettings.tsx`
- `frontend/src/features/staff/panels/DashboardPanel.tsx`
- `frontend/src/features/staff/panels/dashboardLinks.ts`
- `frontend/src/features/staff/panels/shared.tsx`
- `frontend/src/features/staff/staffTabs.moduleGates.test.ts`
- `frontend/src/features/staff/staffTabs.ts`
- `frontend/src/lib/api/types.ts`
- `frontend/src/lib/features.ts`

## Added backend tests (coordinator must run)

- `backend/tests/machines/test_low_stock_procurement_gate.py`: `test_low_stock_never_creates_procurement_until_the_tenant_installs_it`
- `backend/tests/modules/family_helpers.py`: fixture/helper module; no test cases
- `backend/tests/modules/test_family_bookings_only.py`: `test_bookings_only_account_books_ahead_reads_own_history_and_cancels`, `test_bookings_preserves_existing_membership_waiver_and_restriction`
- `backend/tests/modules/test_family_events_only.py`: `test_events_only_create_publish_account_register_offline_settle_checkin`
- `backend/tests/modules/test_family_features.py`: `test_loan_master_switch_has_no_uninstall_or_child_toggle_dependency`, `test_loan_visibility_preserves_retained_loan_policies_and_payment_capabilities`, `test_minimal_profile_audits_publication_even_when_modules_do_not_change`, `test_publication_fields_have_reviewed_export_and_portable_authority`
- `backend/tests/modules/test_family_inventory_only.py`: `test_inventory_only_default_on_account_borrow_and_off_preserves_data`
- `backend/tests/modules/test_family_machines_only.py`: `test_machines_only_public_list_works_without_catalogue_or_membership`
- `backend/tests/modules/test_family_membership_only.py`: `test_membership_only_activity_and_bootstrap_survive_without_loans`
- `backend/tests/modules/test_machine_service_without_machines.py`: `test_global_printer_queue_lists_and_accepts_requests_without_machine_inventory`
- `backend/tests/operations/test_dashboard_family_counts.py`: `test_counts_query_only_enabled_families_and_keep_existing_rows`, `test_event_only_custom_role_gets_its_dashboard_and_cannot_read_another_tenant`, `test_aggregation_failure_is_logged_and_dashboard_stays_available`, `test_event_staff_does_not_gain_hardware_counts_on_a_mixed_tenant`, `test_disabled_loans_do_not_query_inventory_counters`
- `backend/tests/test_public_site_flags.py`: `test_directory_and_embed_key_follow_site_while_catalogue_has_its_own_gate`, `test_machines_module_off_is_a_bad_request`, `test_migration_preserves_old_publication_and_enables_loans`
- Existing backend/tests/makerspaces/test_module_registry.py: added
  test_bookings_never_installs_community_membership.
- Existing backend/tests/modules/test_offstate_facilities.py: replaced dependency-off
  refusal case with test_bookings_works_when_membership_is_off (expects success).
- Existing backend/tests/modules/test_combo_profiles.py and capabilities_defaults.py:
  updated existing profile/dependency/default pins; no new named tests.

## Added frontend tests

- AppRoutes.familyHome.test.tsx: five family homes; explicit preference; disabled
  preference fallback; catalogue flag; site flag; two lazy detail routes; loading (12).
- staffTabs.familyOnly.test.ts: five family consoles; optional loan tabs off; restored
  tabs without reinstalling modules (7).
- MemberArea.moduleGates.test.tsx: five family off-states; stale events deep link;
  enabled PartnerEvents; booking history without membership; enabled Presence (9).
- DashboardPanel.familyOnly.test.tsx: other-family tile suppression across five setups (5).
- Existing staffTabs.moduleGates.test.ts: fixture now explicitly enables loans; existing
  core-spine assertion describes inventory-only with loans on.

## Review pass

Reviewed the complete tracked diff and untracked implementation against the BUILD
GAPS brief, research, repository rules, migration leaf and family contracts. All
changes remain unstaged; only read-only Git commands were used. No events application
code or owner-deferred feature was changed.

### Defects fixed

1. MemberArea contained mojibake in loading text and membership separators. Restored
   the original UTF-8 characters. Normalized all 41 affected CRLF files to LF.
2. Frontend dashboard access still required inventory/machine actions although the
   API now admits programme staff. Added events, bookings, member management and
   finance actions, with non-superadmin custom-role tests.
3. Machine-only classification suppressed independently authorized programme and
   finance queues on mixed roles. Preserve those queues while retaining the existing
   machine row filters; test both machine/programme and machine/finance roles.
4. Dashboard hardware, machine, warranty, email and payment row queries relied only
   on the outer tenant lookup. Routed each staff queryset through RBAC as well.
   Added an outsider aggregation regression.
5. Email failure counters were exposed to inventory readers despite delivery-log
   reads requiring manage_makerspace. Added the matching action gate and a test that
   fails if an unauthorized email queryset is touched. Finance-only staff were
   missing core debt counters; added VIEW_FINANCE admission and counter/tile access
   without requiring the online rail.
6. One failed events aggregation discarded working booking counts. Isolated the
   programme families. Dashboard exception tracebacks/messages could include private
   SQL values; logs now contain tenant/family and error class only. Regression tests
   inject private text and verify that it never enters the log.
7. Disabling loans hid the warranty tab and tile for machines-only spaces, even
   though machine warranty counts stay active. Keep machine warranties reachable;
   add tab/tile assertions for that family.
8. The low-stock procurement module check could race uninstall. Recheck procurement
   while holding the same makerspace row lock as uninstall before creating the item.
   Added a disable-between-check-and-write regression.
9. Public-site settings invalidated public/runtime bootstrap caches but left the
   member portal bootstrap stale. Invalidate that cache too; test real query-cache
   invalidation, the exact PATCH payload and a failed home-setting mutation.
10. Touched directory/status/dashboard schemas omitted authentication/throttle error
    responses; submission omitted the migration-freeze response. Added typed error
    schemas. Also corrected the remaining 33-vs-35 registry count in INVARIANTS.
11. Family coverage missed paid membership admission through offline settlement and
    card issuance, revoked/foreign booking refusals, a stale loan view racing the
    switch, and cross-tenant embed-key refusal. Added those behavioral tests and
    strengthened member off-state tests to wait for the rendered member branch.

Additional manifest entries: frontend/src/features/staff/staffAccess.ts and
frontend/src/features/staff/MakerspacePublicSiteSettings.test.tsx. Updated the
module-family source map for the revised gates and cache behavior.

### Validation

- python -m py_compile: all 55 touched backend Python files passed, including tests
  and the migration. AST parsing also passed.
- npx tsc -b: executed; fails only in the five owner-excluded files. No lane errors.
- npx vitest run: 11 files / 98 tests passed; after the final custom-role and finance
  changes, the affected four staff suites passed 45 tests. Counts overlap.
- git diff --check passed; index empty; AGENTS.md and CLAUDE.md byte-identical.
  All touched text is UTF-8/LF, no detected mojibake/BOM, source files under 300 lines.
- No new model, User FK, task, fan-out entry point, object writer or environment
  variable was introduced. The existing Makerspace fields retain their sibling
  classification, field snapshot and PRESERVE authority entries. No projection reset
  is required. Existing gate_policy declarations remain applicable to the moved
  HTTP views because route identities did not change.
- Backend tests were not executed: host Python has no Django and Docker engine
  access is denied. codex doctor again failed config/home resolution and provider
  reachability, so the separate CLI review gate remains unavailable. The user's
  requested direct review-and-fix pass was completed here; coordinator QA remains.
- Temporary local dependency junctions and build artifacts removed after validation.

### Backend test paths for the coordinator

Run via the isolated scripts/dev.sh test harness after integrating w7-events:

- tests/modules (includes all five test_family_* files, family_features,
  machine_service_without_machines, combo profiles and off-state regressions)
- tests/bookings
- tests/machines/test_low_stock_procurement_gate.py
- tests/operations/test_dashboard_family_counts.py
- tests/test_public_site_flags.py
- tests/makerspaces
- tests/test_capabilities.py
- tests/hardware_requests
- tests/payments/test_rbac_f6_finance.py
- tests/payments/test_admission_settlement.py
- tests/test_apiclient_nonce.py
- tests/test_apiclient_nonce_canonicalization.py
- tests/test_apiclient_scope_enforcement.py
- tests/test_apiclient_enforcement_staging.py
- tests/tombstone/test_procurement_removed_surfaces.py
- tests/data_export/test_registry_guards.py
- tests/data_export/test_portable_audit_references.py
- tests/tenant_migration/test_tenant_dump_catalog_d1.py
- tests/tenant_migration/test_projected_catalog_travel_guard.py
- tests/tenant_migration/test_authority_guard.py
- tests/tenant_migration/test_source_gate_guards.py
- tests/tenant_migration/test_omitted_fields.py
- tests/backup/test_object_field_coverage.py

The previously recorded integration requirements still apply: w7-events supplies
the accounts audience and real detail page; test a real payments_rail tombstone
startup; repin the merged catalog hash and regenerate OpenAPI/types. The stale
events-owned presence-import assertion remains outside this lane.
