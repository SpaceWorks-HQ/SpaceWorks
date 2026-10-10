# w1-payments review handoff

## Review pass

Completed review and direct fixes. Changes remain unstaged; no git state-changing command or database test was run.

Defects found and fixed:

1. Missed advance/due-day notices could say "due today" days late after downtime. They now expire on their scheduled local day; only the latest overdue step catches up once.
2. Billing defaults diverged from the research table. They now use before `[3]`, after `[7]`, cap `2` in both model and migration; the dispatcher reads model defaults instead of a separate fallback. A cap of `3` includes the overdue step; the feature remains off by default.
3. New billing policy/amendment reads bypassed explicit RBAC scopes. Staff policy reads/writes and refund lookup now use action scopes; reminder policy uses scheduled-work scope. Default terms use live internal scope plus explicit actor scope so account-only borrowers and hidden tenants' own staff retain the correct terms.
4. New/changed routes documented only typed business errors although DRF returns field-validation dictionaries too. `schemas_billing.py` declares both response shapes, including nested receipt errors; billing/refund/list/history routes use them.
5. A staff aging filter could remain active after selecting settled payments, yielding an empty result. Changing away from pending now clears aging; a React regression exercises the real query path.
6. F3 edge tests used fabricated membership-term IDs and omitted required creators. They now create real terms and creators. The obsolete payment-module-off parameter was removed because ledger messages are core; the explicit rail-removal regression remains.
7. Reconciliation's refund semantics changed to effective correction heads without a provenance version bump. Its report version is now 4.
8. The new feature had no user-facing feature-table entry. Added `billing.reminders` and split the over-ceiling module guide into linked sibling references, preserving existing inbound anchors. Source map is current.
9. The initial handoff used CRLF. Both handoffs and every changed/new text file now use UTF-8/LF.

Additional validation coverage checks audited correction chains, immutable raw writes/deletes, audit-failure rollback, corrected transfer date ranges, separate currencies and foreign-tenant exclusion, and default terms for account-only/hidden-space workflows.

Validation performed:

- `python -m py_compile`: all changed/new backend Python files compile (including migrations and tests). This is syntax validation only.
- `npx.cmd tsc -b`: exit 0. `npx` initially resolved a PowerShell script blocked by execution policy; the normal `.cmd` launcher succeeded.
- `npx.cmd vitest run` for PaymentBilling, PaymentOfflineRefund, PaymentRefundDialog, PaymentsPanel, PaymentsF6, MemberPayments: 6 files, 22 tests passed.
- `git diff --check`, UTF-8/LF/mojibake scan, 300-line ceiling and AGENTS/CLAUDE byte parity checked.
- No backend test success is claimed. Django is unavailable locally; database infrastructure is inaccessible by instruction.
- `codex doctor` reports unavailable configuration/home and unreachable provider endpoints, so no separate CLI review result is claimed.

Coordinator must run:

```bash
./scripts/dev.sh test tests/payments tests/operations tests/hardware_requests tests/makerspaces tests/tenant_migration tests/test_notification_families_f3.py tests/test_notification_family_edges_f3.py tests/test_capabilities.py
```

Also run migration consistency checks, recompute `tenant_migration.tenant_dump_catalog.CATALOG_SCHEMA_SHA256` against the merged graph (inherited `RECOMPUTE` marker), and regenerate frontend OpenAPI schema/client as reserved in the brief.

Migration: `backend/apps/payments/migrations/0019_billing_due_refund_amendments.py`, dependency `payments.0018_offline_refund_receipt` (actual prior leaf verified). Adds nullable immutable due date/index, refund amendment FK/guards and core billing policy. The review amended this uncommitted migration's default; no additional migration was created.

Skipped: database execution, generated API artifacts and merged catalog pin (coordinator-owned); numbered/tax documents, instalments, member credit, automated cash transfers and deposit offsets remain outside this lane. Owner decisions needed: none for this scope. No new env vars; existing `REMINDER_SWEEP_BATCH_SIZE` is documented in environment-reference.md. No new task/fan-out/object-writing entry point: existing F1 gate_policy_tasks declarations cover the consumer.

Outside findings: inherited catalog `RECOMPUTE` still needs coordinator pinning; initial unrelated `docs/SOURCE-MAP-FRONTEND.md` changes are preserved. Invalid inherited F3 fixtures were corrected because they prevent money-edge regression coverage.

## Full file inventory

Created (`C`) or modified (`M`) relative to the lane base; includes initial implementation and review fixes.

- C: `LANE-PROGRESS.md`
- M: `backend/apps/admin_api/views_email_templates_common.py`
- M: `backend/apps/bookings/service_payments.py`
- M: `backend/apps/data_export/classification_domain.py`
- M: `backend/apps/data_export/datasets.py`
- M: `backend/apps/events/service_payments.py`
- M: `backend/apps/integrations/email_templates_registry_research.py`
- M: `backend/apps/integrations/notification_catalog.py`
- M: `backend/apps/integrations/notifications_research.py`
- M: `backend/apps/integrations/notify.py`
- M: `backend/apps/integrations/recipients_selection.py`
- M: `backend/apps/makerspaces/capabilities.py`
- M: `backend/apps/makerspaces/membership_payments.py`
- M: `backend/apps/makerspaces/membership_plan_services.py`
- M: `backend/apps/operations/org_report_aggregate.py`
- M: `backend/apps/operations/org_report_strategies.py`
- M: `backend/apps/operations/reminder_registry.py`
- M: `backend/apps/operations/reminder_sweeper.py`
- M: `backend/apps/operations/report_definitions_existing.py`
- C: `backend/apps/operations/reports_cash_book.py`
- M: `backend/apps/operations/reports_payments.py`
- M: `backend/apps/operations/schemas_reports.py`
- M: `backend/apps/operations/serializers_reports_payments.py`
- C: `backend/apps/payments/due_dates.py`
- C: `backend/apps/payments/migrations/0019_billing_due_refund_amendments.py`
- M: `backend/apps/payments/models.py`
- C: `backend/apps/payments/models_billing.py`
- M: `backend/apps/payments/models_payment.py`
- M: `backend/apps/payments/models_refund.py`
- M: `backend/apps/payments/notifications.py`
- M: `backend/apps/payments/reconciliation.py`
- C: `backend/apps/payments/reminders.py`
- C: `backend/apps/payments/schemas_billing.py`
- M: `backend/apps/payments/serializers.py`
- M: `backend/apps/payments/serializers_reconciliation.py`
- M: `backend/apps/payments/serializers_refunds_offline.py`
- M: `backend/apps/payments/services.py`
- M: `backend/apps/payments/services_refunds_offline.py`
- M: `backend/apps/payments/urls.py`
- C: `backend/apps/payments/views_billing.py`
- M: `backend/apps/payments/views_member.py`
- M: `backend/apps/payments/views_reconciliation.py`
- M: `backend/apps/payments/views_refunds_offline.py`
- M: `backend/apps/tenant_migration/audit_references_meta_payments.py`
- M: `backend/apps/tenant_migration/money_digest.py`
- M: `backend/apps/tenant_migration/target_projection_fields.py`
- M: `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- M: `backend/apps/tenant_migration/tenant_dump_catalog.py`
- M: `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- M: `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- M: `backend/apps/tenant_migration/unique_values.py`
- C: `backend/apps/tenant_migration/unique_values_billing.py`
- C: `backend/tests/payments/test_billing_due_p5.py`
- C: `backend/tests/payments/test_billing_review.py`
- C: `backend/tests/payments/test_payment_reminders_p6.py`
- C: `backend/tests/payments/test_refund_amendments_p7.py`
- M: `backend/tests/test_notification_families_f3.py`
- M: `backend/tests/test_notification_family_edges_f3.py`
- C: `docs/MODULES-INVENTORY.md`
- C: `docs/MODULES-LIFECYCLE.md`
- C: `docs/MODULES-PLATFORM.md`
- C: `docs/MODULES-WORKSHOPS.md`
- M: `docs/MODULES.md`
- M: `docs/SOURCE-MAP-FRONTEND.md`
- M: `docs/SOURCE-MAP.md`
- C: `docs/payment-billing.md`
- M: `docs/reminder-schedules.md`
- M: `frontend/src/features/members/MemberPayments.tsx`
- C: `frontend/src/features/staff/PaymentBilling.test.tsx`
- C: `frontend/src/features/staff/PaymentDueBadge.tsx`
- M: `frontend/src/features/staff/PaymentOfflineRefund.test.tsx`
- M: `frontend/src/features/staff/PaymentRefundDialog.tsx`
- M: `frontend/src/features/staff/PaymentsPanel.tsx`
- C: `frontend/src/features/staff/RefundReceiptAmendDialog.tsx`
- M: `frontend/src/features/staff/paymentAccess.ts`
- M: `frontend/src/features/staff/paymentsApi.ts`
- M: `frontend/src/lib/features.ts`
- C: `w1-payments-PROGRESS.md`

## Backend test inventory

All tests in new payment test files and modified F3 files; coordinator must execute them. Existing F3 test names are included so fixture repairs are reviewable.

`backend/tests/payments/test_billing_due_p5.py`

- `test_default_terms_snapshotted_on_raise_and_future_policy_never_rewrites_debt`
- `test_aging_and_query_filter_agree_across_local_midnight`
- `test_domain_booking_and_event_start_override_default_terms`
- `test_membership_dues_use_existing_term_start_and_renewal_uses_next_start`
- `test_staff_and_member_lists_sort_by_due_and_refuse_foreign_policy_access`
- `test_billing_and_amendment_catalogs_have_exact_field_coverage`

`backend/tests/payments/test_billing_review.py`

- `test_default_terms_cover_account_only_borrowers_and_hidden_tenant_staff`
- `test_billing_defaults_and_policy_audit_do_not_rewrite_existing_charges`
- `test_refund_corrections_append_audited_chain_without_changing_balance`
- `test_cash_book_dates_follow_corrected_transfer_and_do_not_mix_currency_or_tenant`
- `test_raw_refund_amendments_cannot_branch_or_point_at_another_payment`
- `test_refund_amendment_audit_failure_rolls_back_receipt`

`backend/tests/payments/test_payment_reminders_p6.py`

- `test_due_today_and_overdue_ladder_dispatch_once_only_to_owner`
- `test_due_soon_then_today_are_distinct_idempotent_steps`
- `test_downtime_expires_due_today_and_sends_only_latest_overdue_step`
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

`backend/tests/test_notification_families_f3.py`

- `test_catalog_extends_stable_families_and_every_new_cell_is_default_off`
- `test_templates_validate_and_requester_coverage_is_explicit`
- `test_payment_is_on_commit_and_snapshot_has_no_provider_or_amount`
- `test_rollback_sends_nothing`
- `test_default_off_sends_nothing`
- `test_member_variant_uses_own_address_and_amount_never_reaches_chat`
- `test_member_opt_out_and_revocation_win`
- `test_account_only_payment_owner_can_receive_own_email`
- `test_selected_members_get_staff_body_and_requester_flag_controls_own_variant`
- `test_provider_failure_does_not_escape_on_commit`
- `test_ledger_notifications_survive_rail_removal_before_commit`
- `test_finance_fallback_matches_existing_finance_list_action`
- `test_choice_migration_matches_all_runtime_fields`
- `test_new_template_stream_module_off_is_400`
- `test_payment_templates_remain_available_without_online_rail`

`backend/tests/test_notification_family_edges_f3.py`

- `test_charge_creation_and_offline_settlement_emit_only_after_commit`
- `test_online_settlement_is_idempotent_at_payment_edge`
- `test_waiver_does_not_emit_payment_received`
- `test_late_online_receipt_emits_once_when_waiver_becomes_real_payment`
- `test_successful_refund_emits_once_and_pending_or_failed_do_not`
- `test_offline_refund_emits_after_receipt_transaction`
- `test_membership_decisions_extend_existing_events_and_preserve_welcome`
- `test_low_stock_emits_once_per_existing_restock_edge`
- `test_certification_http_edges_emit_granted_and_revoked`
- `test_type_only_notification_scope_excludes_other_machine_types`
- `test_each_family_module_off_suppresses_delivery`
- `test_existing_maintenance_log_edge_and_module_gate`

## Frontend test changes

- `frontend/src/features/staff/PaymentBilling.test.tsx`: local-day display, overdue staff query, member aging filter, clearing aging on settled status, deposit release route, metadata-only refund correction.
- `frontend/src/features/staff/PaymentOfflineRefund.test.tsx`: deposit release button/dialog regression updated.
