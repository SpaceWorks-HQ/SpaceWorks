# Wave 0 payments — D14 / P7

Implementation complete for coordinator review, all edits unstaged. No test suites run
(Docker/Postgres are unavailable in this lane). Python lacks Django; local frontend
dependencies are absent, but the main checkout's dependencies were used read-only for
TypeScript validation with a compiler host that resolves packages there. No emitted files.
`codex doctor` cannot load config/home and cannot reach the provider, so external CLI
review gates are unavailable; coordinator review/QA remains required.

Completed: core-ledger offline refund endpoint/service and receipt fields on Refund;
append-only database guard, shared balance lock, audit action and OpenAPI annotations;
staff receipt form/action, member refunded total, report totals/version, data-export
classification and tenant-dump field/authority/audit-reference declarations. Extended
money fingerprint to refuse publication after source refunds change. Migration
0018_offline_refund_receipt depends on payments/0017_settlement_cascade.

Static verification: changed Python files parse; every changed file is <=300 lines;
git diff --check is clean; index is empty. TypeScript reported zero diagnostics across
frontend/src. The reconstructed catalog graph reproduces the original HEAD SHA exactly,
and the updated field graph matches the new reviewed catalog pin.

Remaining: coordinator database/migration/runtime tests, normal frontend checks,
independent review and QA. No generated OpenAPI artifacts changed; coordinator must
regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts. Run
makemigrations --check --dry-run, schema checks and the existing refund, reconciliation,
charge-tracking, report, data-export and tenant-migration regression suites, as well as
the new tests below. Run the tombstone test under the full existing tombstone profile.

Decisions: reuse Refund (no new model/FKs/module/feature key). Historical offline money
remains refundable independent of charges/payments feature switches. No legal receipt
numbering, tax credit notes, deposit offsets or member credit in D14 scope.

No owner product decision is required for D14. Formal credit-note numbering remains O1
in the research audit and is outside this receipt-record fix. Pre-upgrade captures that
already contain online refunds require recapture under the expanded money fingerprint;
captures with no refunds keep their original fingerprint until money actually changes.

Outside-scope defect noticed: existing ONLINE Refund immutability protects only status
and amount in model.save; bulk/raw updates and changes to reason/actor/dates remain
possible. The new database trigger fully protects manual rows only, preserving the
existing online webhook lifecycle. This needs a separate rail review.

## Complete file manifest

Created:
- LANE-PROGRESS.md
- backend/apps/payments/exceptions_refunds.py
- backend/apps/payments/migrations/0018_offline_refund_receipt.py
- backend/apps/payments/serializers_refunds_offline.py
- backend/apps/payments/services_refunds_offline.py
- backend/apps/payments/views_refunds_offline.py
- backend/tests/payments/test_offline_refund_integrity.py
- backend/tests/payments/test_offline_refund_reports.py
- backend/tests/payments/test_offline_refunds.py
- frontend/src/features/members/MemberPayments.test.tsx
- frontend/src/features/staff/PaymentOfflineRefund.test.tsx

Modified:
- backend/apps/data_export/classification_domain.py
- backend/apps/operations/org_report_aggregate.py
- backend/apps/operations/org_report_strategies.py
- backend/apps/operations/report_definitions_existing.py
- backend/apps/operations/reports_payments.py
- backend/apps/operations/serializers_reports_payments.py
- backend/apps/payments/models_refund.py
- backend/apps/payments/serializers.py
- backend/apps/payments/serializers_reconciliation.py
- backend/apps/payments/services_refunds.py
- backend/apps/payments/urls.py
- backend/apps/payments/views_member.py
- backend/apps/tenant_migration/audit_references_meta_payments.py
- backend/apps/tenant_migration/money_digest.py
- backend/apps/tenant_migration/tenant_dump_authority_supplement.py
- backend/apps/tenant_migration/tenant_dump_catalog.py
- backend/apps/tenant_migration/tenant_dump_field_snapshot.py
- backend/tests/tombstone/test_payments_removed_surfaces.py
- frontend/src/features/members/MemberPayments.tsx
- frontend/src/features/staff/PaymentRefundDialog.tsx
- frontend/src/features/staff/PaymentsPanel.tsx
- frontend/src/features/staff/panels/OperationsReportsPayments.tsx
- frontend/src/features/staff/paymentsApi.ts

## Added tests (not executed)

backend/tests/payments/test_offline_refunds.py:
- test_cash_deposit_release_without_rail_is_audited_and_payment_stays_unchanged
- test_partial_refunds_allow_the_remainder_and_refuse_any_extra
- test_invalid_receipt_or_amount_writes_nothing (8 cases)
- test_only_offline_settled_money_can_be_recorded_as_returned (4 cases)
- test_scope_subject_authority_and_active_account_are_required
- test_audit_failure_rolls_back_the_refund
- test_member_history_and_reconciliation_report_show_refunded_money_without_join_duplication
- test_refund_after_capture_refuses_publication_and_other_space_does_not_drift

backend/tests/payments/test_offline_refund_integrity.py:
- test_manual_refunds_are_append_only_in_orm_and_database
- test_raw_insert_cannot_skip_receipt_or_over_refund_validation
- test_purge_guard_is_the_only_database_delete_exception
- test_pending_online_attempts_hold_the_same_manual_refundable_balance
- test_concurrent_releases_cannot_refund_the_same_deposit_twice
- test_manual_receipt_fields_and_audit_ids_are_classified_for_export_and_tenant_dump
- test_manual_receipt_survives_csv_and_portable_tenant_projection

backend/tests/payments/test_offline_refund_reports.py:
- test_report_counts_online_and_offline_refunds_but_not_failed_attempts
- test_organization_refund_totals_remain_separate_per_currency

backend/tests/tombstone/test_payments_removed_surfaces.py:
- test_every_ledger_route_still_resolves: added refund-offline route case

frontend/src/features/staff/PaymentOfflineRefund.test.tsx:
- records method, reference and return date through the core endpoint and refreshes reports
- rejects future return dates before recording any money
- offers a refund action for a paid-offline loan deposit in the staff ledger

frontend/src/features/members/MemberPayments.test.tsx:
- shows a member the refunded amount on an offline deposit
