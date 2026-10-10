# w1-payments lane handoff

Implementation and review fixes are complete; all changes remain unstaged. Coordinator database validation is outstanding.

## Completed

- P7: all seven paid_offline charge kinds reuse the core refund receipt. RECORD_PAYMENT gates money-out. Partial refunds and receipt amendments share one locked balance. Method/reference/returned-date corrections append amends rows with PostgreSQL guards; amounts/currencies remain fixed.
- Explicit cash-deposit release requires a returned/closed_with_issue loan. Return evidence and inventory/state workflows stay authoritative. No automatic cash transfer or fee offset is invented.
- Reconciliation/member history use effective refund chain heads. A VIEW_FINANCE cash-book report groups actual manual collection/refund dates by method and currency, including negative net outflows.
- P5: nullable immutable due_at, indexed staff aging filters, local-day derived due_state/due_date, due-sorted lists, default per-space payment terms, domain dates for booking/event/dues/renewals.
- P6: default-OFF billing.reminders, configurable before/after ladder and cap, F1 committed claims with owner-only email dispatch, local DST boundaries, no catch-up storm. Existing charge/received/refund events remain; payer receipt email defaults on subject to explicit matrix OFF. Ledger event/template availability survives rail removal.
- Frontend due badges/filters, dedicated deposit-release mode, manual refund receipt correction dialog, refreshed TanStack Query payment/report caches.
- New billing policy has no accounts.User FK. Existing refund created_by remains declared in references_core.py. Model/field export classification, datasets, portable projection, amendment identity remapping/audit references and money fingerprint are updated. Target reminder policy resets to disabled.

## Migration

- backend/apps/payments/migrations/0019_billing_due_refund_amendments.py
- Dependency: payments.0018_offline_refund_receipt (actual leaf verified before writing).
- Adds Payment.due_at and index, Refund.amends, MakerspaceBillingSettings, updated manual-refund guard and immutable-due-date trigger.

## Coordinator work / validation

- Run ./scripts/dev.sh test tests/payments tests/operations tests/hardware_requests tests/makerspaces tests/tenant_migration tests/test_notification_families_f3.py tests/test_notification_family_edges_f3.py tests/test_capabilities.py (each invocation has its own isolated infrastructure; no shared pytest DB).
- Recompute tenant_migration.tenant_dump_catalog.CATALOG_SCHEMA_SHA256 against the merged graph. The base already had RECOMPUTE; this lane leaves that marker and updates literal model/field/projection declarations.
- Run migration consistency checks and regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts; generation was explicitly reserved for the coordinator.
- Perform code review. codex doctor reported inaccessible provider/config in this sandbox; no CLI review result is claimed.
- Local checks: changed Python files parsed via AST; touched-file ceiling <=300; git diff --check; AGENTS.md/CLAUDE.md byte parity; tsc -b exit 0. No database tests were run and no database success is claimed.
- Focused frontend command executed with exit 0: vitest run PaymentBilling, PaymentOfflineRefund, PaymentRefundDialog, PaymentsPanel, PaymentsF6 and MemberPayments. Coordinator still owns integrated QA.

## Defaults, skips and outside findings

- Owner decisions needed: none for this lane; adopted plan defaults (reminders off, payer email only).
- Tax/numbered documents, instalments, member credit, automatic refund transfers and deposit-to-fee offsets were outside this lane and were not implemented.
- Preserved initial unrelated edit: docs/SOURCE-MAP-FRONTEND.md. No git state-changing commands or generated API edits.
- Review repaired tests/test_notification_family_edges_f3.py: real membership-term subjects and required creators replace fabricated IDs; core payment events no longer use a removable-rail gate test.
- Inherited catalog RECOMPUTE marker and unavailable local Django/Postgres prevent runtime catalog/migration verification here.

## Created files

- `LANE-PROGRESS.md`
- `backend/apps/operations/reports_cash_book.py`
- `backend/apps/payments/due_dates.py`
- `backend/apps/payments/migrations/0019_billing_due_refund_amendments.py`
- `backend/apps/payments/models_billing.py`
- `backend/apps/payments/reminders.py`
- `backend/apps/payments/views_billing.py`
- `backend/apps/tenant_migration/unique_values_billing.py`
- `backend/tests/payments/test_billing_due_p5.py`
- `backend/tests/payments/test_payment_reminders_p6.py`
- `backend/tests/payments/test_refund_amendments_p7.py`
- `docs/payment-billing.md`
- `frontend/src/features/staff/PaymentBilling.test.tsx`
- `frontend/src/features/staff/PaymentDueBadge.tsx`
- `frontend/src/features/staff/RefundReceiptAmendDialog.tsx`

## Modified files (this lane only)

- `backend/apps/admin_api/views_email_templates_common.py`
- `backend/apps/bookings/service_payments.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/datasets.py`
- `backend/apps/events/service_payments.py`
- `backend/apps/integrations/email_templates_registry_research.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/integrations/notifications_research.py`
- `backend/apps/integrations/notify.py`
- `backend/apps/integrations/recipients_selection.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/membership_payments.py`
- `backend/apps/makerspaces/membership_plan_services.py`
- `backend/apps/operations/org_report_aggregate.py`
- `backend/apps/operations/org_report_strategies.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/operations/report_definitions_existing.py`
- `backend/apps/operations/reports_payments.py`
- `backend/apps/operations/schemas_reports.py`
- `backend/apps/operations/serializers_reports_payments.py`
- `backend/apps/payments/models.py`
- `backend/apps/payments/models_payment.py`
- `backend/apps/payments/models_refund.py`
- `backend/apps/payments/notifications.py`
- `backend/apps/payments/reconciliation.py`
- `backend/apps/payments/serializers.py`
- `backend/apps/payments/serializers_reconciliation.py`
- `backend/apps/payments/serializers_refunds_offline.py`
- `backend/apps/payments/services.py`
- `backend/apps/payments/services_refunds_offline.py`
- `backend/apps/payments/urls.py`
- `backend/apps/payments/views_member.py`
- `backend/apps/payments/views_reconciliation.py`
- `backend/apps/payments/views_refunds_offline.py`
- `backend/apps/tenant_migration/audit_references_meta_payments.py`
- `backend/apps/tenant_migration/money_digest.py`
- `backend/apps/tenant_migration/target_projection_fields.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_catalog.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- `backend/apps/tenant_migration/unique_values.py`
- `backend/tests/test_notification_families_f3.py`
- `docs/SOURCE-MAP.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/members/MemberPayments.tsx`
- `frontend/src/features/staff/PaymentOfflineRefund.test.tsx`
- `frontend/src/features/staff/PaymentRefundDialog.tsx`
- `frontend/src/features/staff/PaymentsPanel.tsx`
- `frontend/src/features/staff/paymentAccess.ts`
- `frontend/src/features/staff/paymentsApi.ts`
- `frontend/src/lib/features.ts`

## Added backend tests (coordinator must run)

`backend/tests/payments/test_billing_due_p5.py`

- `test_default_terms_snapshotted_on_raise_and_future_policy_never_rewrites_debt`
- `test_aging_and_query_filter_agree_across_local_midnight`
- `test_domain_booking_and_event_start_override_default_terms`
- `test_membership_dues_use_existing_term_start_and_renewal_uses_next_start`
- `test_staff_and_member_lists_sort_by_due_and_refuse_foreign_policy_access`
- `test_billing_and_amendment_catalogs_have_exact_field_coverage`

`backend/tests/payments/test_payment_reminders_p6.py`

- `test_due_today_and_overdue_ladder_dispatch_once_only_to_owner`
- `test_due_soon_then_today_are_distinct_idempotent_steps`
- `test_disabled_reminders_do_not_claim_or_send`
- `test_default_off_and_maximum_zero_prevent_automatic_mail`
- `test_settlement_and_foreign_subject_are_revalidated_before_dispatch`
- `test_reminders_respect_member_revocation_and_opt_out`
- `test_small_discovery_batches_advance_beyond_scheduled_ladders`
- `test_dst_steps_follow_local_calendar_days`
- `test_payer_receipt_defaults_on_but_explicit_matrix_off_wins`
- `test_receipt_correction_does_not_emit_second_refund_event`

`backend/tests/payments/test_refund_amendments_p7.py`

- `test_append_amendment_keeps_amount_bounds_and_immutable_history`
- `test_amendments_cannot_branch_cross_payments_or_change_money`
- `test_cash_book_uses_effective_methods_and_actual_transfer_dates`
- `test_cash_deposit_is_released_after_real_return_with_rail_off`
- `test_every_charge_kind_supports_cash_refund_without_rail`
- `test_refund_requires_record_payment_even_with_subject_authority`

## Frontend tests and changed regression coverage

`frontend/src/features/staff/PaymentBilling.test.tsx`

- displays the server's local day and queries staff overdue filters
- filters member rows without recomputing dates in the browser timezone
- records a deposit release through the dedicated core route
- corrects a refund receipt without sending a second amount

- frontend/src/features/staff/PaymentOfflineRefund.test.tsx: updated deposit panel regression for Release deposit and Record deposit release.
- backend/tests/test_notification_families_f3.py: added test_payment_templates_remain_available_without_online_rail; renamed/updated test_ledger_notifications_survive_rail_removal_before_commit; repaired creator and real loan-subject fixtures.

## Review pass (2026-10-11)

- Full review record, current file inventory and backend test names: `w1-payments-PROGRESS.md`.
- Fixed stale due-day notices after downtime, reminder policy defaults, explicit RBAC policy/amendment reads, DRF validation response schemas, incompatible staff status/aging filters, invalid F3 fixtures, reconciliation provenance version, missing feature documentation and handoff CRLF.
- Added `backend/tests/payments/test_billing_review.py`, a downtime regression in `test_payment_reminders_p6.py`, and a staff filter regression in `PaymentBilling.test.tsx`.
- Research defaults are now before `[3]`, after `[7]`, cap `2`; raise the cap to `3` for the overdue step. All defaults are documented in `docs/payment-billing.md`.
- Split `docs/MODULES.md` into linked inventory/workshop/platform/lifecycle siblings before updating its feature table; inbound module anchors remain present.
- Available checks: `python -m py_compile` for all changed backend Python files; `npx.cmd tsc -b` exit 0; focused Vitest: 6 files / 22 tests passed; LF/ceiling/UTF-8 checks and AGENTS/CLAUDE byte parity verified.
- Database tests were NOT run. Coordinator must run the backend paths in the review record, pin the merged catalog digest, check migration consistency and regenerate the OpenAPI snapshot/client.
- No new environment variables, tasks, fan-outs or object writers: existing F1 task/fan-out gate declarations cover the registered consumer. No owner decision is required for the scoped work.
