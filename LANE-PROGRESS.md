# Lane w3-receipts

## Review pass

Reviewed the original research/brief, repository/global workflow rules, the complete
tracked diff and every new lane file. Changes remain unstaged; git was read-only.

Defects fixed:

- An existing staff PDF grant bypassed active-account/password-rotation checks and
  browser-origin scoping. Downloads now recheck both as well as VIEW_FINANCE;
  regression tests cover restriction, suspension, deactivation, password rotation
  and a foreign verified tenant origin.
- Finance windows guessed that any midnight timestamp was a calendar filter. This
  shifted rolling schedules ending at UTC midnight. CalendarDateRange now explicitly
  marks date filters; plain rolling tuples retain exact instants. A regression checks
  both revenue and journal inclusion around the midnight boundary.
- The money fingerprint omitted prefix/counter policy when no documents existed.
  It now detects numbering changes before the first receipt, with publication-refusal
  tests for both fields.
- Document validation accepted malformed issuer/line snapshots (including a missing
  label, or negative quantity times negative price) and simultaneous financial sources.
  Model clean and the migration's INSERT trigger now reject them independently;
  tests bypass model save with bulk_create and check the SQL guard's actual error.
  SQL source checks also require the source currency to match the snapshot.
- The global Week selector caused existing coverage previews to request unsupported
  grains. A shared reportGrain helper now chooses the catalog-supported grain for
  preview, export and cache keys; an evidence-report regression covers the fallback.
- Offline report fixtures reused pi_1, violating Payment's globally unique native
  intent key in multi-payment/DST and cross-tenant tests. They now use no native intent.
- The source map and module feature table omitted the lane. Both now describe the
  receipt/report owners, billing.documents, and core/rail/email behavior.
- Twelve lane files still contained CRLF. All touched text is now UTF-8 with LF only;
  the targeted mojibake and production-file line-ceiling checks pass.

Validation after fixes:

- python -m py_compile: all 44 touched backend Python files passed.
- frontend npx.cmd tsc -b: passed. npx.ps1 is blocked by host execution policy;
  the normal Windows .cmd launcher requires no policy change.
- Targeted Vitest: 10 files, 25 tests passed, including receipt UI, billing policy,
  finance charts, coverage grain fallback, report exports/F6, staff payments and
  member/archived payments.
- git diff --check, UTF-8/LF and 300-line production-file checks: passed.
- Migration 0021 still chains off the inspected 0020 payment leaf and makerspaces
  0080. Data-export fields, user/JSON references, projected model/field catalogs,
  authority dispositions and reversal uniqueness were checked against the model.
- No new environment variables, Celery tasks, tenant fan-outs or storage object
  writers were added. PDFs are response bytes; existing settlement/refund boundaries
  and report delivery tasks own writes, so no new gate_policy declarations apply.

Backend runtime checks remain for the coordinator: host Python has no Django, and
Docker has no reachable engine. The SQL/concurrency/backend tests were NOT run here.
codex doctor also reports unavailable config/home and inference connectivity, so a
separate CLI review could not run. No approval, staging, commit or merge was performed.

Coordinator test command (isolated runner):

```bash
./scripts/dev.sh test tests/payments/test_documents.py tests/payments/test_billing_review.py tests/operations/test_finance_reports.py tests/tenant_migration/test_payment_documents_contract.py
```

Also run payment/operations regressions, tests/data_export/test_registry_guards.py,
tests/tenant_migration/test_source_gate_guards.py,
tests/tenant_migration/test_authority_guard.py,
tests/tenant_migration/test_projected_catalog_travel_guard.py,
tests/makerspaces/test_tenant_servability_guard.py and lifecycle-purge coverage.
Run makemigrations --check --dry-run and backend checks; regenerate the OpenAPI
snapshot/client with the pinned backend image; recompute CATALOG_SCHEMA_SHA256 on
the integrated graph (it was already RECOMPUTE before this lane). PDF visual QA and
portable round-trip verification still require that environment.

## Original implementation handoff

Implementation complete; all changes are unstaged. No state-changing git commands were run.

Completed: P1/F7 append-only, numbered receipt/credit-note snapshots and server-side
PDF rendering; payer-only receipt mail through the existing email dispatcher (durable
member-page link); authenticated, user-bound five-minute download grants; settlement,
refund and correction hooks. Added billing presentation/account-code settings and UI.
R1/R2/R5/P16 are registered with VIEW_FINANCE: payments-ledger, revenue-over-time,
cash-book, accounting-journal. Revenue charts separate currencies. Portable export,
user/JSON-reference declarations, field/model catalogs, projection dispositions,
uniqueness and money fingerprint now include financial documents and numbering state.

The sequence is shared across receipt/credit-note kinds per makerspace, as requested.
Correction documents offset and replace originals; existing snapshots never change.
Tax breakdown is nullable, constrained NULL, and unused. Gross-only informal receipts.
Manual dates use received/refunded timestamps; online collection snapshots settlement
Payment.updated_at. Owed is current pending debt grouped by creation date, not a
historical balance. Day/week/month use tenant local time; weeks begin Monday. Legacy
undocumented settlements have an explicit unknown method and updated_at fallback.
Generic balanced cash-basis journal has default account codes, with deposit liability.

Migration: payments/0021_payment_documents.py depends on payments.0020_billing_due_refund_amendments,
makerspaces.0080_membership_admission (actual inspected leaf; needed for historical
feature-field access), and migrations.swappable_dependency(settings.AUTH_USER_MODEL).
It installs the document SQL immutability/integrity trigger, extends billing settings,
creates PaymentDocument and enables billing.documents for existing tenants.
No new dependency: ReportLab already appears in backend/requirements.txt.

Checks performed: changed Python files parsed with ast; all touched files are below
300 lines; document model fields matched literal export classification; git diff
--check; TypeScript noEmit. Frontend Vitest commands were exercised for the new
PaymentDocuments, OperationsReportsFinance and BillingDocumentsSettings tests plus
existing PaymentsPanel, PaymentBilling, MemberPayments and ArchivedPayments tests.
No database tests were run. Host Python lacks Django and ReportLab, so backend runtime,
SQL triggers, migration autodetector and PDF rendering could not be checked here.

Coordinator remaining checks (isolated test runner, not the shared DB):
- ./scripts/dev.sh test tests/payments/test_documents.py tests/operations/test_finance_reports.py tests/tenant_migration/test_payment_documents_contract.py
- Broader payment, operations, data_export, tenant_migration and lifecycle-purge regressions.
- makemigrations --check --dry-run; backend checks; OpenAPI schema generation.
- Recompute tenant_dump_catalog.CATALOG_SCHEMA_SHA256 on the merged graph. Its existing
  value was already RECOMPUTE at lane start; this lane adds another model/field graph.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts (untouched here).
- Render long/escaped receipt and credit-note fixtures to PNG and inspect layout in the
  backend image; document_pdf uses the existing ReportLab Vera font and wrapping tables.
- Review and commit through the coordinator; owner alone merges/pushes.

Skipped/out of scope: tax computation and jurisdiction-specific compliant invoices
(O3 remains undecided; previous no-tax stance retained); vendor-specific accounting
formats/live sync (generic CSV uses the plan's recommendation); PaymentLine/instalments;
retroactive receipt backfill (not requested). Historical settlements remain in ledger/
revenue/cash reports; accounting uses issued documents only. No new module keys.
No owner decision blocks this lane; future tax/legal compliance needs owner decisions.
Mail is link-based rather than a PDF attachment, matching existing report delivery;
users sign in and request a fresh scoped grant. Outbound failures do not undo money.

Outside-task finding: existing terminal_settlement handling for a paid_offline charge
later collected online records payment.double_paid_refund_required, but does not create
an additional collection ledger row. These reports describe recorded ledger money;
that existing double-payment remediation still needs staff handling.

## Created or modified files

- Created: `LANE-PROGRESS.md`
- Modified: `backend/apps/data_export/classification_domain.py`
- Modified: `backend/apps/data_export/datasets.py`
- Modified: `backend/apps/data_export/references_core.py`
- Modified: `backend/apps/data_export/references_json_fields.py`
- Modified: `backend/apps/makerspaces/capabilities.py`
- Modified: `backend/apps/operations/org_report_scope.py`
- Created: `backend/apps/operations/report_definitions_finance.py`
- Modified: `backend/apps/operations/report_registry.py`
- Modified: `backend/apps/operations/report_request_contract.py`
- Modified: `backend/apps/operations/report_schedule_services.py`
- Created: `backend/apps/operations/reports_accounting.py`
- Created: `backend/apps/operations/reports_finance.py`
- Created: `backend/apps/operations/reports_finance_sources.py`
- Modified: `backend/apps/operations/schemas_reports.py`
- Created: `backend/apps/operations/serializers_reports_finance.py`
- Modified: `backend/apps/operations/views_reports.py`
- Created: `backend/apps/payments/document_delivery.py`
- Created: `backend/apps/payments/document_pdf.py`
- Created: `backend/apps/payments/documents.py`
- Created: `backend/apps/payments/migrations/0021_payment_documents.py`
- Modified: `backend/apps/payments/models.py`
- Modified: `backend/apps/payments/models_billing.py`
- Created: `backend/apps/payments/models_documents.py`
- Modified: `backend/apps/payments/reconciliation.py`
- Modified: `backend/apps/payments/schemas_billing.py`
- Modified: `backend/apps/payments/services_refunds.py`
- Modified: `backend/apps/payments/services_refunds_offline.py`
- Modified: `backend/apps/payments/services_webhooks.py`
- Modified: `backend/apps/payments/terminal_settlement.py`
- Modified: `backend/apps/payments/urls.py`
- Modified: `backend/apps/payments/urls_member.py`
- Modified: `backend/apps/payments/views_billing.py`
- Created: `backend/apps/payments/views_documents.py`
- Modified: `backend/apps/tenant_migration/money_digest.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- Modified: `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- Modified: `backend/apps/tenant_migration/unique_values_billing.py`
- Created: `backend/tests/operations/test_finance_reports.py`
- Modified: `backend/tests/payments/test_billing_review.py`
- Created: `backend/tests/payments/test_documents.py`
- Created: `backend/tests/tenant_migration/test_payment_documents_contract.py`
- Created: `docs/payment-documents.md`
- Modified: `frontend/src/features/members/ArchivedPayments.tsx`
- Modified: `frontend/src/features/members/MemberArea.tsx`
- Modified: `frontend/src/features/members/MemberPayments.tsx`
- Created: `frontend/src/features/payments/PaymentDocuments.test.tsx`
- Created: `frontend/src/features/payments/PaymentDocuments.tsx`
- Created: `frontend/src/features/staff/BillingDocumentsSettings.test.tsx`
- Created: `frontend/src/features/staff/BillingDocumentsSettings.tsx`
- Modified: `frontend/src/features/staff/MakerspaceSettingsPanel.tsx`
- Modified: `frontend/src/features/staff/PaymentsPanel.tsx`
- Modified: `frontend/src/features/staff/panels/OperationsReportExports.tsx`
- Modified: `frontend/src/features/staff/panels/OperationsReports.tsx`
- Created: `frontend/src/features/staff/panels/OperationsReportsFinance.test.tsx`
- Created: `frontend/src/features/staff/panels/OperationsReportsFinance.tsx`
- Modified: `frontend/src/features/staff/paymentsApi.ts`
- Modified: `frontend/src/lib/features.ts`

## Backend tests added

`backend/tests/payments/test_documents.py`

- `test_issue_is_transactional_idempotent_and_snapshots_are_not_live`
- `test_rollback_does_not_consume_a_document_number`
- `test_gapless_numbers_under_concurrent_settlements`
- `test_documents_refuse_model_and_database_mutation`
- `test_manual_refund_and_corrections_append_offsetting_documents`
- `test_online_refund_succeeded_once_and_failed_attempt_gets_no_credit`
- `test_provider_settlement_and_replayed_event_issue_one_receipt`
- `test_document_grants_require_finance_or_payment_owner_and_expire`
- `test_mail_is_payer_only_and_failure_cannot_undo_settlement`
- `test_document_append_changes_money_fingerprint`
- `test_disable_issuance_preserves_existing_document_readability`
- `test_disabled_issuance_still_documents_refund_of_a_documented_charge`
- `test_long_escaped_snapshot_renders_a_pdf_without_live_data`
- `test_revoked_payer_and_removed_finance_action_cannot_use_existing_grant`
- `test_billing_document_settings_validate_prefix_mapping_and_keep_counter_private`

`backend/tests/operations/test_finance_reports.py`

- `test_money_totals_match_ledger_after_receipt_and_refund_corrections`
- `test_local_calendar_bucketing_and_date_filter`
- `test_owed_waived_and_online_collected_have_distinct_dates_and_currency`
- `test_accounting_journal_is_balanced_per_currency_and_uses_deposit_liability_mapping`
- `test_registry_header_scoping_view_finance_and_module_off`
- `test_finance_schedule_retains_subject_filters_and_instant_window`
- `test_refund_attempts_are_exported_but_only_succeeded_money_is_totalled`
- `test_both_folds_of_a_dst_day_land_in_the_same_local_bucket`
- `test_historical_offline_money_without_a_receipt_is_not_dropped`

`backend/tests/tenant_migration/test_payment_documents_contract.py`

- `test_document_model_has_complete_portable_field_user_and_ownership_declarations`
- `test_counter_or_prefix_changed_after_capture_refuses_publication`

Existing backend test adjusted: tests/payments/test_billing_review.py,
test_billing_defaults_and_policy_audit_do_not_rewrite_existing_charges, now expects
the additive settings fields and a counter created by receipt issuance.

## Frontend tests added

- features/payments/PaymentDocuments.test.tsx: staff/member authenticated download grant;
  denied grant displays an error and does not fetch bytes.
- features/staff/panels/OperationsReportsFinance.test.tsx: sums subjects within a period
  while keeping USD/INR collected/owed/refunded charts separate; requests week grain.
- features/staff/BillingDocumentsSettings.test.tsx: saves only document/mapping fields,
  preserving billing terms; malformed mapping JSON never reaches the server.
