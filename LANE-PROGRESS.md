# w2-loans progress

Implementation complete; coordinator validation and generated schema refresh remain.

## Completed

- F5 optional loan policy with validated periods, renewal caps/mode/length, borrow ceilings, signed reminder offsets and staff escalation. Missing rows preserve legacy defaults and reminders.
- Product/category period and renewal-cap inheritance; membership-plan borrow-limit overrides. Defaults remain opt-in for renewal/limits.
- Member and ACCEPT_REQUEST-scoped staff renew through the workflow barrel: active/lapsed/waiting/cap checks, tenant-first row locks, due-date extension, linked loan synchronization and audit; no new states.
- F1 borrower ladder and F3 staff escalation use scoped queries, local F4 rendering, permanent claims, due-only fair discovery, live revalidation and new occurrence identities after due changes. Existing hourly/cron/task/management entry points share the ladder.
- Limits enforced in Inventory Availability at submission and actual handover, including rejected quantities and outstanding returned/damaged/missing units. Returns retain photo and remark requirements.
- Staff policy form, member renewal control and staff active-queue action use mutations with cache invalidation. Member activity now includes reviewed loans.
- OpenAPI annotations, export classification/dataset/User-FK decision, tenant catalog/field snapshots/projection and audit presentation are updated.

## Validation and coordinator work

- Python AST parsing of every changed Python file completed; touched files remain below 300 lines.
- Frontend `node node_modules/typescript/bin/tsc -b --pretty false` completed successfully. This is compilation, not test execution.
- `git diff --check` completed without whitespace errors. No git state-changing commands were run; changes remain unstaged.
- Before this review, no backend or frontend tests were executed. See Review pass for the frontend results; database tests remain unrun.
- Read-only parallel review completed with no remaining blockers after fixes to waiting-item joins, staff eligibility, rejected-quantity limits, lock order, editable date templates and discovery fairness.
- Coordinator must run the new test files below, existing member_activity, operations, reminder/task/cron, direct-loan, self-checkout, request-workflow, capabilities/schema, audit, data_export and tenant_migration regressions through the isolated runner.
- Coordinator must regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts after integration and check migration consistency.
- `codex doctor` could not load configuration/reach the provider in this sandbox; coordinator must run external CLI review/QA gates.
- Inherited tenant_dump_catalog.py has CATALOG_SCHEMA_SHA256="RECOMPUTE" from Wave 1. Coordinator must pin the digest from the full merged model graph; no guessed digest was written.

## Migrations (actual leaves inspected)

- makerspaces/0080_makerspace_loan_policy.py -> makerspaces/0079_staff_invitations_feature: policy plus MembershipPlan ceilings.
- inventory/0012_loan_period_overrides.py -> inventory/0011_inventoryproduct_deposit_amount: nullable Category/InventoryProduct periods and renewal caps.
- hardware_requests/0028_loan_renewal_count.py -> hardware_requests/0027_kiosk_replay_resolution: renewal counter.

## Scope and owner decisions

- No owner decisions needed for implemented scope; stated defaults used.
- Staff-approval renewals, new request states, reservation/expiry/waitlist mechanisms and other top-10 items remain Wave 4/out of scope.
- Generated OpenAPI artifacts and test execution are intentionally left to the coordinator as instructed.
- Nullable product/category/plan overrides have staff API support; additional editors for these overrides were not added. The requested per-space bundle has a complete staff form.
- No new module keys; AGENTS.md and CLAUDE.md were not edited.

## Outside-task observations

- Existing docs/SOURCE-MAP-FRONTEND.md has an unrelated profile/settings documentation change; preserved. Loan UI ownership references were added to docs/SOURCE-MAP.md instead.
- The inherited catalog digest marker above is an integration validation dependency, not silently treated as a passing guard.

## Files created

- `LANE-PROGRESS.md`
- `w2-loans-PROGRESS.md`
- `backend/apps/accounts/rbac_borrowers.py`
- `backend/apps/admin_api/serializers_loan_policy.py`
- `backend/apps/admin_api/views_loan_policy.py`
- `backend/apps/hardware_requests/loan_reminder_notifications.py`
- `backend/apps/hardware_requests/loan_reminders.py`
- `backend/apps/hardware_requests/migrations/0028_loan_renewal_count.py`
- `backend/apps/hardware_requests/renewal_views.py`
- `backend/apps/hardware_requests/renewal_workflow.py`
- `backend/apps/inventory/availability_loan_limits.py`
- `backend/apps/inventory/migrations/0012_loan_period_overrides.py`
- `backend/apps/makerspaces/loan_policy.py`
- `backend/apps/makerspaces/member_loans.py`
- `backend/apps/makerspaces/migrations/0080_makerspace_loan_policy.py`
- `backend/apps/makerspaces/models_loan_policy.py`
- `backend/apps/operations/reminder_types.py`
- `backend/apps/tenant_migration/tenant_dump_authority_loans.py`
- `backend/tests/hardware_requests/loan_policy_helpers.py`
- `backend/tests/hardware_requests/test_loan_policy.py`
- `backend/tests/hardware_requests/test_loan_policy_handovers.py`
- `backend/tests/hardware_requests/test_loan_policy_schema.py`
- `backend/tests/hardware_requests/test_loan_reminder_ladder.py`
- `backend/tests/hardware_requests/test_loan_renewal_concurrency.py`
- `backend/tests/hardware_requests/test_loan_renewals.py`
- `backend/tests/hardware_requests/test_loan_review_regressions.py`
- `docs/loan-policy.md`
- `frontend/src/features/members/MemberLoanRenew.test.tsx`
- `frontend/src/features/members/MemberLoanRenew.tsx`
- `frontend/src/features/staff/MakerspaceLoanPolicySettings.test.tsx`
- `frontend/src/features/staff/MakerspaceLoanPolicySettings.tsx`
- `frontend/src/features/staff/StaffLoanRenew.test.tsx`
- `frontend/src/features/staff/StaffLoanRenew.tsx`

## Files modified

- `backend/apps/accounts/rbac.py`
- `backend/apps/admin_api/serializers_inventory_products.py`
- `backend/apps/admin_api/serializers_makerspace_aux.py`
- `backend/apps/admin_api/serializers_membership_plans.py`
- `backend/apps/admin_api/views_makerspaces.py`
- `backend/apps/audit/presentation_catalog_hardware.py`
- `backend/apps/audit/presentation_catalog_makerspaces.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/datasets.py`
- `backend/apps/data_export/references_core.py`
- `backend/apps/hardware_requests/direct_loan_returns.py`
- `backend/apps/hardware_requests/direct_loan_workflow.py`
- `backend/apps/hardware_requests/handover_workflow.py`
- `backend/apps/hardware_requests/models.py`
- `backend/apps/hardware_requests/request_workflow.py`
- `backend/apps/hardware_requests/return_workflow.py`
- `backend/apps/hardware_requests/self_checkout_issue.py`
- `backend/apps/hardware_requests/serializers.py`
- `backend/apps/hardware_requests/services_return_reminders.py`
- `backend/apps/hardware_requests/urls.py`
- `backend/apps/hardware_requests/workflow.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/inventory/availability.py`
- `backend/apps/inventory/models.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/member_activity_serializers.py`
- `backend/apps/makerspaces/member_activity_service.py`
- `backend/apps/makerspaces/models.py`
- `backend/apps/makerspaces/models_makerspace.py`
- `backend/apps/makerspaces/models_membership_plans.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/tenant_migration/authority_guards.py`
- `backend/apps/tenant_migration/gate_policy_tasks.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/target_projection_rows.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- `backend/tests/member_activity/test_member_activity.py`
- `docs/SOURCE-MAP.md`
- `docs/SOURCE-MAP-FRONTEND.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/members/MemberActivity.tsx`
- `frontend/src/features/staff/MakerspaceGeneralSettings.tsx`
- `frontend/src/features/staff/panels/Queues.tsx`
- `frontend/src/lib/features.ts`

## Build tests (backend unrun; frontend results below)

- `backend/tests/hardware_requests/loan_policy_helpers.py`
  - Shared setup helper; no test functions.
- `backend/tests/hardware_requests/test_loan_policy.py`
  - `test_policy_rejects_invalid_boundaries`
  - `test_policy_model_validates_offsets_and_defaults_without_creating_row`
  - `test_policy_patch_is_scoped_audited_and_keeps_legacy_days_coherent`
  - `test_period_and_cap_inherit_product_then_category_then_space`
  - `test_loan_policy_is_classified_without_user_closure`
  - `test_borrow_limits_are_opt_in_and_count_outstanding_items`
  - `test_current_plan_overrides_borrow_limits`
  - `test_issue_limit_counts_only_items_actually_handed_over_after_rejects`
  - `test_policy_endpoint_answers_400_when_workflow_module_is_off`
- `backend/tests/hardware_requests/test_loan_policy_handovers.py`
  - `test_direct_bundle_uses_shortest_product_period_and_borrow_limit_rolls_back_stock`
  - `test_public_checkout_uses_policy_period_and_refuses_second_active_loan`
- `backend/tests/hardware_requests/test_loan_policy_schema.py`
  - `test_loan_policy_and_renewal_routes_document_inputs_and_errors`
- `backend/tests/hardware_requests/test_loan_reminder_ladder.py`
  - `test_before_due_due_and_overdue_steps_are_idempotent_and_borrower_only`
  - `test_timezone_rendering_and_elapsed_offsets_across_dst`
  - `test_escalation_emits_f3_staff_event_once_without_borrower_copy`
  - `test_returned_rescheduled_and_removed_steps_are_revalidated`
  - `test_renewal_creates_new_occurrence_without_replaying_old_steps`
  - `test_no_policy_keeps_existing_reminder_behavior`
  - `test_opt_in_does_not_repeat_legacy_zero_step`
  - `test_completed_older_loans_do_not_starve_later_loans_with_small_batch`
  - `test_ladder_never_builds_cross_tenant_subject`
  - `test_unverified_contact_is_not_used_as_borrower_address`
  - `test_source_module_gates_keep_borrower_mail_independent_of_staff_inbox`
  - `test_custom_date_template_keeps_datetime_type_and_makerspace_zone`
  - `test_hourly_entry_point_dispatches_policy_ladder_without_legacy_duplicate`
  - `test_future_overdue_step_does_not_starve_newly_due_loan`
- `backend/tests/hardware_requests/test_loan_renewal_concurrency.py`
  - `test_concurrent_renewals_cannot_exceed_policy_or_emit_two_audits`
- `backend/tests/hardware_requests/test_loan_renewals.py`
  - `test_member_renewal_extends_both_due_dates_without_status_transition_and_audits`
  - `test_staff_renewal_uses_the_same_policy_and_can_renew_reviewed_loans`
  - `test_ineligible_staff_cannot_renew_another_borrowers_loan`
  - `test_renewal_refusals_leave_due_date_and_audit_unchanged`
  - `test_other_members_and_other_tenants_cannot_renew`
  - `test_member_renew_module_or_feature_off_returns_400`
  - `test_dashboard_includes_reviewed_loans_and_renewal_eligibility`
  - `test_accepted_request_with_matching_declined_item_does_not_block_renewal`
  - `test_partial_return_does_not_block_on_already_returned_product`
  - `test_future_membership_term_cannot_authorize_renewal`
  - `test_manual_due_change_keeps_linked_loan_coherent_without_using_renewal_slot`
  - `test_renewal_rejects_non_object_payload_without_audit`
  - `test_renewal_refuses_datetime_overflow_without_changing_due_date`
  - `test_staff_renewal_checks_browser_origin_even_with_authority_in_both_spaces`
- `frontend/src/features/members/MemberLoanRenew.test.tsx`
  - renews the owned loan and refreshes member activity
  - shows policy refusal without invalidating cached activity
  - allows another policy-approved renewal after activity refreshes the due date
- `frontend/src/features/staff/MakerspaceLoanPolicySettings.test.tsx`
  - saves the policy with signed offsets and refreshes settings
  - rejects duplicated offsets before making a request
  - shows a scoped or module gate error
- `frontend/src/features/staff/StaffLoanRenew.test.tsx`
  - renews through the staff route and refreshes queues and timeline

## Existing tests adjusted

- backend/tests/member_activity/test_member_activity.py: make_loan fixture now matches an issued request/due date; owned projection assertion covers the new renewal fields. Other tests unchanged.


## Review pass (2026-10-11)

Completed a strict review of the brief, existing handoff, all tracked diff hunks,
untracked implementation/tests and relevant invariants. The requested named progress
file was absent, so w2-loans-PROGRESS.md now mirrors this complete lane handoff.

Defects fixed:

1. The fan-out registry still named run_return_reminders after its gate loop moved
   into _run_legacy_return_reminders. Updated gate_policy_tasks.py to the actual
   caller; a stdlib AST comparison found no missing or stale fan-out entries.
2. Loan policy/override/counter fields lacked explicit migration authority decisions.
   Added tenant_dump_authority_loans.py, unioned it into the catalog and authority
   guard. Terms travel under target-owned feature gates; consumed renewal slots
   remain history, so migration cannot silently replenish them.
3. Legacy reminders could use stale discovery rows after a return, due-date edit
   or policy opt-in. They now use RBAC scheduled scope and re-read eligibility
   inside the tenant boundary before claiming. All legacy marker writes are scoped.
4. A ladder attempt stamped the legacy sent marker even when email was suppressed
   or failed, and channel failures looked like successful F1 completions. The marker
   now requires delivered borrower email; failed channel results create a terminal
   failed claim without automatic retry. Documented the delivery/claim distinction.
5. The member-renew test's expression-bodied beforeEach returned its mock as a
   cleanup callback; Vitest invoked it after the refusal test and rejected. Changed
   it to a block-bodied hook. The refusal test now passes without weakening it.
6. A successful member renewal left the button disabled for the life of the row,
   including when policy allowed more renewals. The control is keyed to the due
   date, resetting only when refreshed server activity confirms a new occurrence.
7. Normalized all changed lane text to UTF-8 without BOM and LF. No changed file
   exceeds 300 lines; no replacement-character/common mojibake markers were found.

New review test functions in backend/tests/hardware_requests/test_loan_review_regressions.py:

- test_undelivered_zero_step_keeps_legacy_marker_empty_and_claim_permanent (2 cases)
- test_legacy_reminder_revalidates_after_discovery (3 cases)
- test_loan_fanout_declarations_match_the_actual_gate_callers
- test_borrow_item_limit_excludes_returned_damaged_and_missing_units
- test_new_loan_authority_fields_preserve_terms_and_consumed_renewals

Frontend regression added to MemberLoanRenew.test.tsx:
- allows another policy-approved renewal after activity refreshes the due date

Validation:
- python -m py_compile succeeded for all 63 changed/new backend Python files,
  including migrations and tests.
- frontend npx.cmd tsc -b --pretty false succeeded. npx.ps1 was initially blocked
  by the Windows execution policy; the normal .cmd shim required no policy change.
- frontend npx.cmd vitest run on MemberLoanRenew.test.tsx,
  MakerspaceLoanPolicySettings.test.tsx and StaffLoanRenew.test.tsx: 3 files,
  7 tests passed after fixing the hook and adding the multi-renewal regression.
- git diff --check passed; AGENTS.md and CLAUDE.md remain byte-identical.
- No database tests ran; no database behavior is claimed verified. No staging,
  commits, branch changes, merges, generated schema edits or outside-tree edits.

Coordinator must run backend/tests/hardware_requests/test_loan_{policy,
policy_handovers,policy_schema,reminder_ladder,renewal_concurrency,renewals,
review_regressions}.py plus backend/tests/member_activity and existing reminder,
workflow, direct-loan, self-checkout, operations, capability/schema, audit,
data_export and tenant_migration suites. In particular run
backend/tests/tenant_migration/test_source_gate_guards.py and test_authority_guard.py.

No new migration, module key or environment variable was needed in this review.
The three build migrations and their actual-leaf dependencies remain listed above.
No owner decision is needed for this scope. Wave 4 states/reservations/staff approval,
backend execution, generated OpenAPI refresh and the merged catalog digest remain
with the coordinator. The inherited CATALOG_SCHEMA_SHA256="RECOMPUTE" marker is an
outside-task integration defect: it must be pinned against the merged graph before
catalog tests can pass. No digest was guessed from this isolated lane.

Outside-task Windows path defect: Git tracks both docs/SOURCE-MAP-FRONTEND.md and
docs/SOURCE-MAP-frontend.md with different contents. They alias one physical file
on this checkout. Kept the pre-existing uppercase-path diff, placed new loan UI
references in SOURCE-MAP.md, and left the naming repair to the coordinator.
