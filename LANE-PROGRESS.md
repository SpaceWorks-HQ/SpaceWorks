# w1-profile — research foundation F4

Implemented: Makerspace timezone/country/opening_hours fields; deployment TIME_ZONE
backfill; strict IANA/ISO/schedule validators; UTC-boundary local-time service;
MANAGE_MAKERSPACE-scoped profile GET/PATCH with typed validation, transactional audit,
and the existing payment currency default; public timezone/hours only; settings editor
with weekly intervals and dated exceptions; export/reference/catalog declarations.

Migration: makerspaces/0077_makerspace_location_profile.py depends on
makerspaces/0076_station_operator_leases.py (actual leaf inspected).

Coordinator must run backend tests (not run here: no Django/Docker/Postgres):
- tests/makerspaces/test_local_time.py — DST gaps/folds, day lengths, half-hour
  transitions, skipped dates, exceptions, weekly search, aware-input contract.
- tests/makerspaces/test_profile_validation.py — zones/country/schedule validation.
- tests/makerspaces/test_profile_api.py — validation, tenant/action scope, audit
  rollback, shared currency with existing charges unchanged, public privacy, portable projection and live catalog.
- tests/makerspaces/test_profile_concurrency.py ? existing-row and first-insert lock coordination.
- tests/makerspaces/test_profile_schema.py ? partial PATCH, typed errors, auth and public privacy.
- tests/makerspaces/test_profile_migration.py — deployment-zone backfill.
- Existing data_export, tenant_migration catalog/projection, makerspace settings,
  platform bootstrap and OpenAPI guards; regenerate API artifacts centrally.

Frontend tests added: MakerspaceProfileSettings.test.tsx (9 editor/API/cache/errors,
accessibility, partial-PATCH, tenant-switch cache isolation and schedule serialization/validation checks).
Executed: frontend TypeScript build-mode check; targeted editor Vitest; Python AST
syntax and code-file ceiling checks; git diff whitespace check. Final recheck complete. Backend tests remain unrun.

Catalog hash updated from the literal snapshots; the reconstructed prior graph
exactly reproduced ff05f198… before adding the three fields. Live validate_catalog
is still mandatory in coordinator tests.

No feature/module key, extra model or User FK was introduced. Empty hours preserve
the plan default (always open). Currency shares the existing payment-settings row.
No booking/reminder/report policy was changed. Deferred staff date consumers:
- panels/machine/MaintenanceSchedules.tsx: creation's next_due defaults to UTC today
  (`new Date().toISOString().slice(0, 10)`). This changes stored dates, not just display.
- panels/OperationsReportsMembers.tsx: "today" describes current-state aggregates;
  converting report semantics is explicitly outside this lane.
- MembersPanel.tsx, InvitationRequestsSection.tsx, MemberTermsDialog.tsx and the
  LedgerParts/CardsTable/WarrantyPanel date formatters use browser-local presentation.
  They need a shared tenant-zone formatter and propagation in the later consumer lane.

Owner decisions: none required within this lane's brief. Backfill uses deployment
TIME_ZONE per the Wave 1 table. Unrelated product proposals remain out of scope.

Environment: codex doctor reports configuration/home unavailable and unreachable
provider endpoints; nested CLI gates cannot run. Changes remain unstaged.

Outside-task risk noticed during review: the existing payment-settings route uses
get_or_create BEFORE calling its update service, so the earlier handoff's claim that
that route passes an unsaved instance was incorrect. However, the model's save()
runs full_clean(), which can turn a concurrent first-insert uniqueness race into a
Django ValidationError that get_or_create does not catch. The existing endpoint does
not catch it either. This pre-existing risk is outside this lane; it has not been
reproduced here (backend tests cannot run). The profile creator handles both DB
uniqueness recovery and the model-validation case.

## Complete changed-file inventory

- `backend/apps/admin_api/serializers_makerspaces.py`
- `backend/apps/admin_api/urls_makerspaces.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/references_json_fields.py`
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/makerspaces/origin_scope_routes.py`
- `backend/apps/makerspaces/platform.py`
- `backend/apps/makerspaces/views.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_catalog.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/requirements.txt`
- `docs/INVARIANTS.md`
- `docs/SOURCE-MAP.md`
- `frontend/src/features/staff/MakerspacePaymentSettings.tsx`
- `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- `frontend/src/lib/api/types.ts`
- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_makerspace_profile.py`
- `backend/apps/admin_api/views_makerspace_profile.py`
- `backend/apps/makerspaces/local_time.py`
- `backend/apps/makerspaces/migrations/0077_makerspace_location_profile.py`
- `backend/apps/makerspaces/opening_hours_schema.py`
- `backend/apps/makerspaces/profile_validation.py`
- `backend/tests/makerspaces/test_local_time.py`
- `backend/tests/makerspaces/test_profile_api.py`
- `backend/tests/makerspaces/test_profile_concurrency.py`
- `backend/tests/makerspaces/test_profile_schema.py`
- `backend/tests/makerspaces/test_profile_migration.py`
- `backend/tests/makerspaces/test_profile_validation.py`
- `frontend/src/features/staff/MakerspaceHoursEditor.tsx`
- `frontend/src/features/staff/MakerspaceProfileSettings.test.tsx`
- `frontend/src/features/staff/MakerspaceProfileSettings.tsx`
- `frontend/src/features/staff/makerspaceProfileForm.ts`

## Added test inventory (backend tests are NOT executed)

`backend/tests/makerspaces/test_local_time.py`:

- `test_local_day_bounds_cover_real_dst_days`
- `test_day_bounds_contain_exactly_the_local_date_across_transitions`
- `test_to_local_retains_fold_and_instant`
- `test_local_now_uses_the_makerspace_zone`
- `test_naive_instants_are_rejected`
- `test_fold_opens_first_occurrence_and_closes_last_half_open`
- `test_gap_moves_opening_forward_by_gap`
- `test_interval_wholly_in_spring_gap_collapses`
- `test_overlapping_fold_expansion_merges_intervals`
- `test_empty_hours_always_open_and_holiday_exception_replaces_day`
- `test_closed_week_and_far_future_special_opening`
- `test_multiple_intervals_and_exceptions_override_weekly`
- `test_skipped_date_does_not_produce_an_open_interval`
- `test_far_exception_near_max_date_does_not_overflow_weekly_search`

`backend/tests/makerspaces/test_profile_api.py`:

- `test_profile_get_does_not_create_settings_and_works_without_modules`
- `test_profile_patch_uses_existing_currency_authority_and_audits_only_fields`
- `test_currency_default_creates_one_settings_row_and_is_shared_with_payment_route`
- `test_validation_is_typed_400_and_atomic`
- `test_cross_tenant_manager_cannot_read_or_write_profile`
- `test_verified_tenant_origin_can_use_own_profile_but_cannot_cross_tenants`
- `test_inventory_manager_has_no_profile_action`
- `test_archived_and_hidden_makerspaces_are_not_profile_targets`
- `test_audit_failure_rolls_back_profile_and_currency`
- `test_public_bootstrap_exposes_zone_and_hours_but_not_country`
- `test_profile_fields_and_currency_travel_in_portable_projection`

`backend/tests/makerspaces/test_profile_migration.py`:

- `test_timezone_backfill_uses_deployment_timezone`

`backend/tests/makerspaces/test_profile_validation.py`:

- `test_iana_zones_are_accepted`
- `test_unknown_zones_are_rejected`
- `test_default_uses_deployment_timezone`
- `test_complete_country_allowlist_and_blank`
- `test_invalid_countries_are_rejected`
- `test_bad_interval_structures_are_rejected`
- `test_bad_schedule_structures_are_rejected`
- `test_closed_days_adjacent_intervals_midnight_and_holidays_are_valid`

`frontend/src/features/staff/MakerspaceProfileSettings.test.tsx`:

- loads and saves country, zone, multiple intervals and a holiday; refreshes related server state
- blocks overlapping intervals before sending a mutation
- sends only edited fields so a timezone edit cannot overwrite payment currency or hours
- can close a day and remove an exception without losing other days
- shows typed field errors and retains the editable draft
- keeps an old save response in its own tenant cache after switching makerspaces
- round-trips always-open and explicit closed schedules
- rejects duplicate/invalid dates, overnight and malformed times, permits 24:00


## Review pass

Completed a strict review of the full tracked diff and all added files against the
brief, plan defaults, RBAC, audit, public exposure and migration/export contracts.

Defects fixed:
- next_open_interval searched only one weekly cycle; a DST-erased opening could
  return None even though the following week opens. Search now covers two cycles,
  still bounded by exception count; added second-cycle and prolonged-closure tests.
- First currency creation held the makerspace FOR UPDATE lock before inserting the
  payment row. A competing insert can hold its unique-index entry while waiting for
  the root's FK key-share lock, causing a deadlock. Creation now precedes the root
  lock and existing settings lock first. Competing full_clean uniqueness failures
  are recovered by reading the winner. Added real first-insert concurrency coverage;
  moved the existing concurrency test to its own sibling file.
- A caught payment validation failure could commit an earlier default-row creation.
  The typed-error branch now rolls back its transaction; regression asserts neither
  that row nor profile fields nor audit entries survive.
- Malformed JSON used DRF's untyped ParseError response despite the documented 400.
  It now uses invalid_profile with non_field_errors. Added endpoint coverage.
- Source-gate 423/503 responses were absent from the profile schema. Added their
  typed schema and schema-generation regressions for partial writes and privacy.
- Profile payment queries now also call rbac.scope_by_action explicitly, in addition
  to being filtered by the already scoped tenant root.
- Saving currency in the payment editor left profile server state stale. Payment
  saves now invalidate the profile query; a two-panel test verifies the visible
  currency refreshes without requiring a profile save.
- Python's Unicode-aware digit regex accepted HH:MM strings the JS editor rejected.
  Backend validation and OpenAPI now require ASCII digits; added invalid-digit input.
- Seven changed/new files had CRLF; all changed files were normalized to UTF-8 LF.
  Expanded SOURCE-MAP to describe the frontend editor and shared-currency refresh.

Additional tests (not run on backend):
- test_local_time.py: test_search_reaches_second_cycle_when_dst_erases_next_weekly_opening;
  test_search_crosses_holiday_closures_longer_than_a_week.
- test_profile_api.py: test_noop_patch_does_not_create_settings_or_audit_rows;
  test_malformed_json_is_a_typed_profile_error_without_writes;
  test_inactive_access_status_blocks_profile_reads_and_writes;
  test_quiesced_source_gate_blocks_profile_patch_but_keeps_reads;
  test_profile_patch_is_core_with_all_optional_modules_off;
  test_payment_validation_failure_rolls_back_created_row_and_profile.
- test_profile_concurrency.py: test_profile_currency_and_payment_settings_edits_serialize_without_losing_fields
  (moved); test_first_profile_currency_save_serializes_with_first_payment_settings_save.
- test_profile_schema.py: test_profile_schema_documents_partial_patch_and_error_shapes;
  test_public_schema_exposes_only_public_profile_fields.
- test_profile_validation.py: test_schedule_size_limits_are_enforced; Unicode digit
  case added to test_bad_interval_structures_are_rejected.
- MakerspaceProfileSettings.test.tsx: refreshes profile currency when payment settings
  save the shared default (the 9th test).

Validation completed: python -m py_compile on all 23 touched backend Python files;
frontend npx.cmd tsc -b; npx.cmd vitest run for MakerspaceProfileSettings.test.tsx
and MakerspacePaymentSettings.test.tsx (2 files, 12 tests passed); git diff --check;
UTF-8/LF and <=300-line code-file checks. PowerShell blocks npx.ps1; npx.cmd ran the
same commands successfully. No database tests were run or reported as passing.

Coordinator must run all six backend files listed above plus data_export drift,
tenant_migration catalog/projection/source-gate, bootstrap and settings regressions.
In particular live validate_catalog and the new concurrency/schema tests remain
unverified until that run. Regenerate the two frontend API artifacts centrally.
Migration remains 0077_makerspace_location_profile, depending on the actual prior
leaf 0076_station_operator_leases; no additional migration was needed in review.

No new model/User FK, module/feature key, env variable, task/fan-out or object writer
was introduced. Existing model classification, JSON-reference declaration, raw-field
snapshot and explicit PRESERVE authority entries cover all three added fields.
The HTTP source gate recognizes the route via origin_scope_routes and the standard
JWT/middleware boundaries, so no gate_policy exemption is required.

Remaining: coordinator backend execution and generated artifacts. Staff date
consumers remain deferred as listed above; booking/reminder/report behavior is outside
this foundation lane. No owner decision is needed. codex doctor was rechecked:
configuration/home and provider reachability remain unavailable, so nested CLI gates
are blocked. All changes remain unstaged; no git state-changing commands were run.
