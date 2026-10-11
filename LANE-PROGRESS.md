# w3-analytics - implementation ready for coordinator verification

## Completed

- R7: canonical `member-retention` report. Join-month cohorts, default 3/6/12-month
  anniversaries (configurable 1-120), mature denominators, retained/churned/reactivated
  member counts. Lifecycle audits recover reactivations; timestamp fallback supports
  legacy records. No names, emails, IDs of members, plan labels or internal reasons.
- R8: canonical `membership-revenue` report. Local month-end (or range-end/current-time)
  recurring-term snapshots, monthly price or annual price / 12, MRR/ARR/ARPU by currency,
  distinct recurring members, churn and reactivation from coverage gaps. Contiguous
  renewals do not count as churn. Cancelled terms retain history up to audited cancellation.
  Money outputs round after ARR is calculated. Overlapping terms count one member once
  per currency; the latest starting term wins. Hidden tenants stay absent from deployment
  aggregates but remain readable by their own authorized staff.
- R11: reuses w5-lists `operations.SavedView` with `entity=report`; no new model.
  State holds registered report key, date/enum/anniversary filters, grain and allow-listed
  columns. Personal ownership, manager-authorized makerspace sharing, owner and reader
  reauthorization, paginated APIs, transactional audited writes, feature gating, source
  freeze coverage and report-module purge integration. Staff-list views remain independent.
  Frontend uses server preferences and refetches a shared view on open; columns affect
  preview only, preserving the registry-defined export shape and provenance.
- R12: validated conditions (non-empty; sum of a curated numeric metric compared to a
  threshold), evaluated before file creation. Multi-currency thresholds select a currency.
  Role slugs and action keys resolve recipients at send time through RBAC, with active
  account, local membership, notification opt-out and report-authority checks. New staff
  email-list targets are refused in favor of live selectors. Existing explicit lists keep
  their compatibility path, with current local account authorization rechecked.
  Uses existing private-link delivery, audited skips and claim-before-work idempotency.
  Schedule editor preserves pinned filters while conditions/recipients change; exports
  select a grain supported by the report being downloaded.
- Added `reports.saved_views` (default ON), backend/frontend definitions, existing-space
  backfill, OpenAPI request/response/error definitions and reports module documentation.
- Updated schedule data-export fields, non-reference JSON declarations and tenant field
  snapshot. Existing schedule DROP and saved-view RESET projections are reused.

## Migrations

- `backend/apps/operations/migrations/0012_report_schedule_rules.py`
  depends on `operations.0011_saved_view`; adds condition, role-slug and action JSON fields.
- `backend/apps/makerspaces/migrations/0081_report_saved_views_feature.py`
  depends on `makerspaces.0080_membership_admission`; backfills the default-ON feature for
  existing reports-enabled makerspaces. Both dependencies were checked against actual leaves.

## Verification and remaining coordinator work

- Database tests were not run: Docker/Postgres are unavailable to this lane. No backend
  test result is claimed. Run the three new backend files plus relevant existing regressions:
  `./scripts/dev.sh test tests/operations/test_membership_analytics.py tests/operations/test_report_schedule_rules.py tests/operations/test_saved_report_views.py tests/operations/test_report_schedules.py tests/operations/test_saved_views.py tests/operations/test_report_exports_fablab.py tests/operations/test_report_provenance.py tests/operations/test_org_report_aggregation.py`
- Also run capability, module purge, OpenAPI, source-gate, data-export and tenant-catalog guards.
- Executed targeted frontend Vitest checks covering new views/rules/preview and existing
  schedules/finance delegation. TypeScript build checking completed with exit code 0.
  Parsed changed Python files with AST; checked touched file ceilings and diff whitespace.
- Coordinator regenerates frontend OpenAPI artifacts and recomputes the tenant catalog digest.
  The base already has `CATALOG_SCHEMA_SHA256 = "RECOMPUTE"`; this lane does not bless a merged graph.
- Nested CLI review cannot run here: `codex doctor` reports home/config resolution and
  provider connectivity failures. Coordinator review and database QA remain required.
- All edits are inside this worktree and unstaged. No git state-changing command was run.

## Skipped / owner decisions / outside defects

- No owner decisions block this lane. Definitions above follow the requested counts-only
  and recurring-plan projection defaults.
- Historical price snapshots do not exist: MRR is a current-price projection, not a
  historical collected-revenue ledger. Current term-waiver state is also used.
- Custom-day plans have no monthly recurrence and are excluded. A cancelled term without
  a cancellation timestamp cannot establish historical coverage and is excluded.
- Legacy lifecycle audit history may be incomplete; available membership timestamps are
  the fallback. Churn reasons and per-person reports are outside the counts-only brief.
- New membership reports are excluded from organization combined totals because distinct
  members and local-time snapshots cannot be flattened safely; deployment output keeps
  makerspace IDs. No PDF digest, BI builder, tax/receipts or other-lane money work was added.
- Existing browser-local saved report presets were not imported automatically; staff can
  save server views explicitly. Saved views are per-makerspace, as specified, not deployment-wide.
- Review correction: `payment-cash-book` is present in the current organization
  STRATEGIES. The earlier outside-defect note is stale and does not describe this tree.

## Created files

- `LANE-PROGRESS.md`
- `backend/apps/makerspaces/migrations/0081_report_saved_views_feature.py`
- `backend/apps/operations/membership_report_history.py`
- `backend/apps/operations/membership_report_scope.py`
- `backend/apps/operations/migrations/0012_report_schedule_rules.py`
- `backend/apps/operations/report_condition_metrics.py`
- `backend/apps/operations/report_definitions_membership.py`
- `backend/apps/operations/report_schedule_rules.py`
- `backend/apps/operations/reports_membership_revenue.py`
- `backend/apps/operations/reports_retention.py`
- `backend/apps/operations/serializers_report_views.py`
- `backend/apps/operations/serializers_reports_membership.py`
- `backend/apps/operations/views_report_views.py`
- `backend/tests/operations/test_membership_analytics.py`
- `backend/tests/operations/test_report_schedule_rules.py`
- `backend/tests/operations/test_saved_report_views.py`
- `frontend/src/features/staff/panels/ReportScheduleRules.test.tsx`
- `frontend/src/features/staff/panels/SelectedReportPreview.test.tsx`
- `frontend/src/features/staff/panels/SelectedReportPreview.tsx`
- `frontend/src/features/staff/panels/ServerReportViews.test.tsx`
- `frontend/src/features/staff/panels/ServerReportViews.tsx`
- `frontend/src/features/staff/panels/reportViewsApi.ts`

## Modified files

- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/guards.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/module_purge_collectors_reports.py`
- `backend/apps/makerspaces/module_purge_plans.py`
- `backend/apps/operations/admin_report_schedules.py`
- `backend/apps/operations/models_report_schedules.py`
- `backend/apps/operations/org_report_scope.py`
- `backend/apps/operations/report_registry.py`
- `backend/apps/operations/report_request_contract.py`
- `backend/apps/operations/report_schedule_services.py`
- `backend/apps/operations/reports.py`
- `backend/apps/operations/schemas_reports.py`
- `backend/apps/operations/serializers_report_catalog.py`
- `backend/apps/operations/serializers_report_schedules.py`
- `backend/apps/operations/urls.py`
- `backend/apps/operations/views_report_helpers.py`
- `backend/apps/operations/views_reports.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `docs/MODULES.md`
- `frontend/src/features/staff/panels/OperationsReportExports.tsx`
- `frontend/src/features/staff/panels/OperationsReports.tsx`
- `frontend/src/features/staff/panels/ReportScheduleForm.tsx`
- `frontend/src/features/staff/panels/ReportSchedules.test.tsx`
- `frontend/src/features/staff/panels/ReportSchedules.tsx`
- `frontend/src/features/staff/panels/operationsReportsConfig.ts`
- `frontend/src/features/staff/panels/reportSchedulesApi.ts`
- `frontend/src/lib/features.ts`

## Added backend test names (all require coordinator execution)

`backend/tests/operations/test_membership_analytics.py`

- `test_cohort_uses_local_join_month_and_only_mature_anniversaries`
- `test_cohort_recovers_original_join_and_reactivation_from_append_only_audits`
- `test_mrr_normalizes_yearly_plans_keeps_currencies_separate_and_counts_members_once`
- `test_mrr_churn_reactivation_and_contiguous_renewals`
- `test_mrr_local_snapshot_includes_term_starting_before_local_month_end`
- `test_analytics_scope_module_off_and_aggregate_pii_absence`
- `test_retention_filter_validation_and_mrr_default_month_grain`
- `test_hidden_makerspace_staff_can_read_their_report_without_deployment_disclosure`
- `test_mrr_preserves_cancelled_term_history_only_until_audited_cancellation`
- `test_legacy_join_timestamp_survives_a_later_role_only_approval`
- `test_annual_projection_rounds_outputs_after_computing_arr`

`backend/tests/operations/test_report_schedule_rules.py`

- `test_condition_threshold_sums_numeric_rows`
- `test_non_empty_ignores_header_and_currency_threshold_never_sums_currencies`
- `test_condition_contract_rejects_invalid_or_non_numeric_metrics`
- `test_unmet_condition_advances_once_audits_skip_and_never_creates_an_object`
- `test_live_role_and_action_recipients_stop_after_revocation_and_deduplicate`
- `test_recipient_resolution_respects_opt_out_restriction_and_report_authority`
- `test_schedule_api_validates_role_tenant_action_and_metric_and_allows_dynamic_only`
- `test_legacy_explicit_local_staff_address_stops_receiving_after_revocation`
- `test_new_schedule_staff_targets_use_live_selectors_instead_of_addresses`
- `test_non_empty_condition_skip_uses_the_same_schedule_path`

`backend/tests/operations/test_saved_report_views.py`

- `test_private_report_view_round_trip_reuses_saved_view_and_audits_every_write`
- `test_shared_report_view_reauthorizes_reader_and_owner_and_refuses_peer_writes`
- `test_saved_report_view_tenant_module_and_feature_gates`
- `test_saved_report_state_rejects_pii_unknown_columns_invalid_ranges_and_unsupported_reports`
- `test_report_saved_views_are_paginated_and_portable_preferences_reset`
- `test_source_freeze_blocks_report_preference_writes_and_allows_reads`
- `test_only_manager_may_share_and_report_readers_cannot_open_finance_views`

## Added frontend tests

`frontend/src/features/staff/panels/ReportScheduleRules.test.tsx`

- allows dynamic recipients without a frozen address and carries a numeric condition
- offers curated metrics and submits the non-empty rule
- preserves pinned filters while editing conditions and replaces dates with a moving window

`frontend/src/features/staff/panels/SelectedReportPreview.test.tsx`

- uses the monthly report grain and displays only saved columns

`frontend/src/features/staff/panels/ServerReportViews.test.tsx`

- saves report filters and columns on the server and refreshes the list
- reauthorizes a shared view on open and displays a revoked-owner error
- deletes a saved report and refreshes server state

The existing `ReportSchedules.test.tsx` expected create payload was updated for empty condition/selector defaults; its existing test cases are unchanged.

## Review pass

Reviewed the brief, repository/global instructions, handoff, full tracked diff and new files.
All work remains unstaged; only read-only git commands were used.

Defects fixed:

1. Saved MRR views without an explicit grain defaulted to unsupported `day`. They now
   default from the report registry (`month`); partial column edits preserve that state.
2. MRR churn/reactivation could include events before a mid-month range start. Monthly
   event windows now intersect the requested interval while preserving month-end MRR.
3. Schedules accepted report-specific filters that the runner silently ignored. A shared
   allow-list now validates saved views and schedules; changing reports in the editor
   clears old report-specific filters and retains calendar dates/the moving window.
4. Editing a legacy schedule with its unchanged staff email list failed validation.
   Existing addresses may be retained; newly added local staff addresses still require
   live role/action selectors, and delivery still reauthorizes legacy local recipients.
5. Schedule list/detail discovery, recipient legacy-role lookup, destination field lookup,
   due claims and expiry scans had queries outside RBAC. These now use action-based or
   scheduled-work scope before lookup. Destination scope includes every report action.
6. Export buttons used the previously selected report's filter suffix. Export parameters
   now come from the clicked report, including its supported grain and relevant filters.
7. A presign failure after successful storage lost the object key. FAILED delivery rows
   now retain the stored key and expiry so cleanup can remove the object.
8. Expiry cleanup cleared the key even after a failed storage delete. The storage helper
   now reports failure and the sweeper preserves the key for retry. Existing object-writer
   gate participation remains valid; no new task, fan-out or writer was introduced.
9. Broad scheduler exception traces could log sensitive upstream error text. Structured
   logs and delivery errors now contain IDs and exception class names only.
10. Invalid calendar dates (and a maximum-date overflow) could raise 500. Date parsing and
    boundary conversion now return a DRF validation 400.
11. Schedule filter schema, schedule authentication/write-gate error responses and saved
    view pagination documentation were incomplete. Typed filter annotations, 401/423/503
    responses and the `page` parameter are now declared.
12. Capability tests pinned stale counts/defaults and positional charge assumptions.
    Assertions now cover the current 25 features, saved views and existing invitation
    defaults, plus the explicit six charge defaults. Added a real module-off feature test.
13. SOURCE-MAP documentation was missing and the detailed reports-module page omitted the
    new behaviour/purge scope. Both now describe the implementation. Removed the stale
    cash-book finding above and normalized all touched text files to LF.

Regression coverage added for all behavioural fixes, selective report-view purge,
schedule selector DROP authority/projection, failed object-delete retries and secret-free
failure logging. The three lane test files remain the primary database regression paths;
`backend/tests/test_capabilities.py` also changed.

Verification:

- `python -m py_compile` executed on every touched backend Python file.
- `npx.cmd tsc -b`: passed (PowerShell blocks `npx.ps1`; the equivalent CMD shim works).
- `npx.cmd vitest run`: 8 files, 23 tests passed, covering ReportScheduleRules,
  ReportSchedules, SelectedReportPreview, ServerReportViews, OperationsReportExports,
  OperationsReportsF6, OperationsReportCharts and OrganizationAnalyticsPanel.
- Confirmed touched production files are <=300 lines, UTF-8 with no mojibake, LF only;
  `git diff --check` clean; AGENTS.md and CLAUDE.md remain byte-identical.
- No new environment variables, models or accounts.User FKs. Existing SavedView export
  classification/user-edge/RESET rules are reused. All three new schedule fields appear
  in export classification, JSON declarations and the tenant field snapshot, and inherit
  the model's explicit DROP authority and projection (new regression asserts this).
- Migration dependencies still point at the actual prior leaves. Tenant graph digest
  remains the inherited `RECOMPUTE`; coordinator must pin the final integrated graph.
- Database tests and schema generation cannot execute here: local Python has no Django
  and Docker has no running daemon. No backend test pass is claimed. Generated frontend
  OpenAPI artifacts remain pending coordinator regeneration from drf-spectacular >=0.30.
- `codex doctor` was rerun: configuration/home resolution and provider reachability fail.
  The nested CLI gate is unavailable; this direct requested review/fix pass is completed.

Coordinator commands (after verifying the container mounts this tree):

```bash
./scripts/dev.sh test tests/operations/test_membership_analytics.py tests/operations/test_report_schedule_rules.py tests/operations/test_saved_report_views.py tests/operations/test_report_schedules.py tests/operations/test_saved_views.py tests/operations/test_report_exports_fablab.py tests/operations/test_report_provenance.py tests/operations/test_org_report_aggregation.py tests/test_capabilities.py tests/makerspaces/test_module_purge.py tests/data_export/test_registry_guards.py tests/tenant_migration/test_tenant_dump_catalog_d1.py tests/tenant_migration/test_source_gate_guards.py tests/tenant_migration/test_source_gate.py tests/tenant_migration/test_source_gate_p2b.py
```

Also run the coordinator's OpenAPI/tenant-catalog/source-gate checks, regenerate
`frontend/openapi-schema.json` and `frontend/src/generated/api.ts`, and pin the merged
catalog digest. New review files: `serializers_report_views_filters.py`; modified beyond
the original inventory: `report_delivery_storage.py`, `views_report_schedules.py`,
`tenant_dump_catalog.py`, `tests/test_capabilities.py`, `docs/SOURCE-MAP.md`,
`docs/MODULES-PLATFORM.md` and `OperationsReportExports.test.tsx`.
