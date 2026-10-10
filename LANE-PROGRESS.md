# w1-membership - review complete, coordinator database validation pending

All lane changes remain unstaged. No git state-changing commands or database tests ran.
`docs/SOURCE-MAP-FRONTEND.md` was already modified on arrival; this lane did not edit it.

## Review pass (2026-10-11)

Detailed review changes, added tests and the complete review file inventory are in
`w1-membership-PROGRESS.md`. The original implementation inventory follows below.

- Fixed the vouch endpoint's invalid RBAC keyword and scoped its request lookup.
- Revocation now cancels unpaid admission charges without altering settled receipts.
- Claimed community invitations notify staff; staff claims bypass community forms.
- Reviewer payment summaries require VIEW_FINANCE; applicant debt remains visible.
- Voucher reads use MANAGE_MEMBERS scope, including capability mutation responses.
- Export predicates reject foreign selected plans and admission-payment edges.
- Private join answers reset when navigating between makerspaces.
- Existing active-member role attachments retain established updates, including when
  new admissions are closed. New or inactive members still face admission gates.
- Application-export GET audit writes and direct settlement activation now take
  tenant write boundaries. New admission schemas document gate 423/503 responses.
- Corrected settings copy about live conditions and snapshots; normalized six files
  to LF and repaired damaged punctuation in this handoff.
- Added `backend/tests/makerspaces/test_membership_admission_review.py` (8 functions,
  10 parameterized cases) and one export-query regression in the existing lane test.
- Added frontend cases for staff claims without answers and tenant navigation reset.
- Verification: `python -m py_compile` succeeded on all 104 changed backend Python
  files; static source-gate totality succeeded; `npx.cmd tsc -b` exited 0; focused
  Vitest passed 27 files / 102 tests; `git diff --check` succeeded. The index is empty,
  all changed files use LF, code files obey the ceiling except accepted settings.py,
  and AGENTS.md/CLAUDE.md remain byte-identical and unchanged.
- Backend database tests, migration execution/drift, generated schema/client and
  browser QA remain coordinator work. No new migration, module key or env var was
  introduced by this review. No owner decision remains open.

## Completed

- Five admission modes, editable recipes, compatibility backfill and legacy PATCH aliases.
- Immutable tenure/limit/expiry-checked vouches, flag-only accountability and reviewer visibility.
- Encrypted form answer snapshots, private own/reviewer reads and owned application export.
- First-term plus joining-fee admission debt, default plans and once/each-join joining-fee rules.
- Request-level awaiting_payment; committed online/offline/waived settlement activates through the shared service.
- Expiry/cancellation, replacement-vouch recovery, restricted rejoin debt access and pending walk-in handling.
- F3 receipt/decision/payment notices, F1 due reminders and both scheduler registrations with tenant write gates.
- Settings/join/invitation/reviewer/dashboard/walk-in React surfaces, scoped OpenAPI route annotations.
- Export/encryption/user-FK/purge/tenant portability catalogs; imported admission authority remains inert.
- Explicit barrels split membership services, checkout and the over-ceiling tenant authority catalog.
- Payment-related joins lock only their intended rows, preserving admission makerspace then payment lock order.

## Verification and work remaining

- Frontend: `tsc --noEmit --incremental false -p tsconfig.json` exited 0.
- Focused Vitest: 16 files, 64 tests passed (all seven new files and nine related existing files).
- Static Python AST parsing and whitespace checks succeeded; touched files are below 300 lines except the established Django settings exception.
- AGENTS.md/CLAUDE.md are byte-identical and unchanged; the git index is empty.
- Database tests, migrations and schema drift checks were NOT run: Django/Docker/Postgres are unavailable here, and the lane forbids database runs.
- Coordinator: run isolated tests for makerspaces, payments, operations, data_export, encryption, tenant_migration and apiclients; include the existing scheduled-task and membership regressions.
- Coordinator: run makemigrations --check --dry-run and migration forward/reverse checks on Postgres 16.
- Coordinator: regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts; neither was edited here.
- Coordinator: recompute/pin tenant_migration/tenant_dump_catalog.py CATALOG_SCHEMA_SHA256 after all lanes integrate; RECOMPUTE was already present in the base.
- Coordinator: perform browser QA and the mandatory review gate. codex doctor was unavailable in this sandbox (home/config resolution and HTTP reachability).
- No staging, commits, merging or pushing by this lane.

## Migrations

- makerspaces/0080_membership_admission.py: makerspaces.0079_staff_invitations_feature; payments.0019_membership_request_subject; encryption.0007_tenant_import_fence_operation; swappable AUTH_USER_MODEL.
- payments/0019_membership_request_subject.py: payments.0018_offline_refund_receipt (choices-only).

## Decisions, limits and unrelated defects

- No outstanding owner decision: vouch defaults use the stated research proposal and accountability stays flag-only.
- Native applicant payment retains existing active-membership device grants; hosted checkout and offline receipts provide the admission payment paths.
- Deactivated admission plans keep already-settled requests pending until the plan is available; collected money remains in the ledger.
- Existing ordinary hosted checkout lacks the history endpoint's unrestricted-account predicate; left outside this lane.
- Existing revoked-member Presence button remains visible although its endpoint refuses the action; left outside this lane.

## Every created file

- `LANE-PROGRESS.md`
- `backend/apps/admin_api/views_membership_admission.py`
- `backend/apps/makerspaces/membership_admission.py`
- `backend/apps/makerspaces/membership_admission_direct.py`
- `backend/apps/makerspaces/membership_admission_forms.py`
- `backend/apps/makerspaces/membership_admission_notifications.py`
- `backend/apps/makerspaces/membership_admission_payments.py`
- `backend/apps/makerspaces/membership_admission_settings.py`
- `backend/apps/makerspaces/membership_helpers.py`
- `backend/apps/makerspaces/membership_legacy.py`
- `backend/apps/makerspaces/membership_vouching.py`
- `backend/apps/makerspaces/migrations/0080_membership_admission.py`
- `backend/apps/makerspaces/models_admission.py`
- `backend/apps/makerspaces/serializers_admission.py`
- `backend/apps/makerspaces/views_admission.py`
- `backend/apps/operations/membership_payment_reminders.py`
- `backend/apps/operations/reminder_types.py`
- `backend/apps/operations/tasks_admissions.py`
- `backend/apps/payments/admission_access.py`
- `backend/apps/payments/admission_settlement.py`
- `backend/apps/payments/checkout_coordination.py`
- `backend/apps/payments/checkout_provider.py`
- `backend/apps/payments/migrations/0019_membership_request_subject.py`
- `backend/apps/payments/subject_validation.py`
- `backend/apps/tenant_migration/tenant_dump_authority_entries.py`
- `backend/tests/data_export/test_membership_admission.py`
- `backend/tests/makerspaces/test_membership_admission_api.py`
- `backend/tests/makerspaces/test_membership_admission_lifecycle.py`
- `backend/tests/makerspaces/test_membership_admission_matrix.py`
- `backend/tests/makerspaces/test_membership_admission_vouches.py`
- `backend/tests/operations/test_membership_payment_reminders.py`
- `backend/tests/payments/test_admission_payment_locking.py`
- `backend/tests/payments/test_admission_settlement.py`
- `backend/tests/payments/test_rejoin_admission_access.py`
- `docs/membership-admission.md`
- `frontend/src/features/members/AdmissionJoin.test.tsx`
- `frontend/src/features/members/AdmissionJoin.tsx`
- `frontend/src/features/members/MemberAdmission.test.tsx`
- `frontend/src/features/members/MemberAdmission.tsx`
- `frontend/src/features/members/MemberAreaAdmission.test.tsx`
- `frontend/src/features/members/MemberInvitationAdmission.test.tsx`
- `frontend/src/features/members/membershipAdmissionApi.ts`
- `frontend/src/features/staff/MembershipAdmissionReview.test.tsx`
- `frontend/src/features/staff/MembershipAdmissionReview.tsx`
- `frontend/src/features/staff/MembershipAdmissionSettings.test.tsx`
- `frontend/src/features/staff/MembershipAdmissionSettings.tsx`
- `frontend/src/features/staff/WalkInMemberForm.test.tsx`

## Every modified file

- `backend/apps/admin_api/serializers_makerspace_mutations.py`
- `backend/apps/admin_api/serializers_member_memberships.py`
- `backend/apps/admin_api/services_staff.py`
- `backend/apps/admin_api/urls_memberships.py`
- `backend/apps/admin_api/views_member_memberships.py`
- `backend/apps/admin_api/views_walk_in.py`
- `backend/apps/apiclients/scope_registry_routes.py`
- `backend/apps/data_export/archive.py`
- `backend/apps/data_export/classification_domain.py`
- `backend/apps/data_export/datasets.py`
- `backend/apps/data_export/fields.py`
- `backend/apps/data_export/references_core.py`
- `backend/apps/data_export/references_json_fields.py`
- `backend/apps/encryption/registry.py`
- `backend/apps/integrations/email_templates_registry_research.py`
- `backend/apps/integrations/notification_catalog.py`
- `backend/apps/integrations/notifications_research.py`
- `backend/apps/makerspaces/apps.py`
- `backend/apps/makerspaces/capabilities.py`
- `backend/apps/makerspaces/invitation_request_services.py`
- `backend/apps/makerspaces/lifecycle_purge.py`
- `backend/apps/makerspaces/member_activity_views.py`
- `backend/apps/makerspaces/membership_activation.py`
- `backend/apps/makerspaces/membership_revocation.py`
- `backend/apps/makerspaces/membership_services.py`
- `backend/apps/makerspaces/models.py`
- `backend/apps/makerspaces/models_roles.py`
- `backend/apps/makerspaces/module_purge_collectors_membership.py`
- `backend/apps/makerspaces/module_purge_plans.py`
- `backend/apps/makerspaces/serializers_memberships.py`
- `backend/apps/makerspaces/urls.py`
- `backend/apps/makerspaces/views_invitation_requests.py`
- `backend/apps/makerspaces/views_membership_invitations.py`
- `backend/apps/makerspaces/views_memberships.py`
- `backend/apps/makerspaces/walk_in_services.py`
- `backend/apps/operations/management/commands/run_scheduled_tasks.py`
- `backend/apps/operations/reminder_registry.py`
- `backend/apps/operations/reminder_sweeper.py`
- `backend/apps/operations/tasks.py`
- `backend/apps/payments/availability.py`
- `backend/apps/payments/credential_validation.py`
- `backend/apps/payments/member_access.py`
- `backend/apps/payments/member_scope.py`
- `backend/apps/payments/models_payment.py`
- `backend/apps/payments/reconciliation.py`
- `backend/apps/payments/reconciliation_authority.py`
- `backend/apps/payments/services_checkout.py`
- `backend/apps/payments/services_connect_webhooks.py`
- `backend/apps/payments/services_mobile.py`
- `backend/apps/payments/services_refunds.py`
- `backend/apps/payments/services_refunds_offline.py`
- `backend/apps/payments/services_webhooks.py`
- `backend/apps/payments/subjects.py`
- `backend/apps/payments/terminal_settlement.py`
- `backend/apps/payments/views_member.py`
- `backend/apps/tenant_migration/audit_references_meta_membership.py`
- `backend/apps/tenant_migration/gate_policy_tasks.py`
- `backend/apps/tenant_migration/references.py`
- `backend/apps/tenant_migration/target_projection_fields.py`
- `backend/apps/tenant_migration/target_projection_rows.py`
- `backend/apps/tenant_migration/tenant_dump_authority.py`
- `backend/apps/tenant_migration/tenant_dump_authority_supplement.py`
- `backend/apps/tenant_migration/tenant_dump_field_snapshot.py`
- `backend/apps/tenant_migration/tenant_dump_model_catalog.py`
- `backend/apps/tenant_migration/tenant_dump_source_projection.py`
- `backend/apps/tenant_migration/tenant_dump_user_rows.py`
- `backend/apps/tenant_migration/unique_values_core.py`
- `backend/config/settings.py`
- `backend/tests/makerspaces/test_invitation_requests.py`
- `docs/SOURCE-MAP-DOMAINS.md`
- `docs/SOURCE-MAP.md`
- `docs/reminder-schedules.md`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberReferrals.tsx`
- `frontend/src/features/staff/MakerspaceMembershipSettings.tsx`
- `frontend/src/features/staff/MembersPanel.tsx`
- `frontend/src/features/staff/WalkInMemberForm.tsx`
- `frontend/src/lib/features.ts`

## Every added backend test function (coordinator must run)

- `backend/tests/data_export/test_membership_admission.py`: `test_admission_models_and_user_edges_have_complete_export_classification`; `test_admission_dataset_refuses_foreign_plan_or_request`; `test_readable_export_redacts_application_free_text`; `test_unrecognized_application_answers_fail_closed_in_readable_export`; `test_unpaid_application_transports_as_canceled_history_with_its_charge`; `test_unapproved_application_and_vouches_cannot_transfer_admission_authority`; `test_stub_applicant_answers_are_removed_without_decryption`; `test_application_answers_encrypt_and_readable_export_decrypts_then_redacts`; `test_membership_purge_removes_admission_evidence_but_preserves_core_members`
- `backend/tests/makerspaces/test_membership_admission_api.py`: `test_application_schema_validates_private_snapshot_reviewer_and_own_export`; `test_admission_settings_rbac_foreign_plan_and_recipe_overrides`; `test_unpaid_expiry_cancels_charge_and_releases_open_request_slot`; `test_applicant_cancellation_ownership_and_module_off_400`; `test_backfill_copies_all_old_policies_without_opt_in_or_plan`; `test_preconfiguration_application_keeps_its_submission_policy`; `test_pending_payment_approval_http_has_request_shape_and_foreign_actor_is_refused`; `test_voucher_response_never_contains_private_answers_or_payment`; `test_existing_settings_patch_fields_remain_aliases_after_configuration`; `test_configured_invitation_cannot_bypass_claim_form_and_payment_by_staff_approval`; `test_module_off_suspends_admission_expiry_without_altering_core_memberships`
- `backend/tests/makerspaces/test_membership_admission_lifecycle.py`: `test_rejoin_dues_rule_records_a_fresh_subject_without_double_charging`; `test_walk_in_paid_before_activation_waits_for_offline_receipt`; `test_walk_in_answers_and_approval_do_not_give_front_desk_decision_authority`; `test_walk_in_http_pending_shape_and_closed_refusal_roll_back_person_creation`; `test_membership_off_keeps_core_walk_in_and_staff_invitation_behaviour`; `test_admission_family_addresses_the_owned_applicant_including_pending_rejoin`; `test_outbound_notice_failure_never_rolls_back_awaiting_payment`; `test_configured_core_creation_keeps_the_existing_space_manager_protection`; `test_core_settings_authority_does_not_replace_the_membership_approval_action`
- `backend/tests/makerspaces/test_membership_admission_matrix.py`: `test_mode_price_and_payment_timing_condition_matrix`; `test_first_term_and_joining_fee_form_one_snapshotted_charge`; `test_invitation_claim_requires_and_snapshots_application_answers`; `test_closed_refuses_every_join_path_with_typed_error`; `test_free_before_activation_succeeds_with_charge_tracking_disabled`; `test_foreign_manager_cannot_approve_or_raise_admission_charge`
- `backend/tests/makerspaces/test_membership_admission_vouches.py`: `test_vouch_quorum_still_requires_staff_approval_by_default`; `test_only_active_unrestricted_local_members_with_enough_tenure_can_vouch`; `test_legacy_member_tenure_uses_creation_when_activation_timestamp_is_missing`; `test_pending_applicant_limit_is_released_when_an_application_activates`; `test_duplicate_vouch_and_model_or_database_edits_are_refused`; `test_expired_vouch_no_longer_counts_or_occupies_pending_capacity`; `test_vouch_can_replace_approval_but_cannot_replace_payment`; `test_settlement_rechecks_vouchers_and_replacement_recovers_paid_admission`; `test_revocation_flags_vouchers_without_restricting_them`
- `backend/tests/operations/test_membership_payment_reminders.py`: `test_payment_reminder_dispatches_applicant_family_once_and_advances_bounded_batch`; `test_live_payment_reminder_refuses_changed_subject`; `test_module_off_never_sends_payment_reminder`; `test_custom_dispatch_is_after_fresh_module_check`; `test_admission_sweep_is_registered_and_calls_domain_service`
- `backend/tests/payments/test_admission_payment_locking.py`: `test_checkout_reexport_preserves_scheduled_checkout_patch`; `test_offline_settlement_leaves_joined_makerspace_unlocked`
- `backend/tests/payments/test_admission_settlement.py`: `test_offline_or_waive_resumes_only_after_commit`; `test_all_gateway_settlements_schedule_admission_resume`; `test_activation_failure_keeps_committed_receipt_and_logs_no_personal_data`; `test_money_received_after_waiver_also_resumes_admission`; `test_rolled_back_settlement_does_not_resume`; `test_membership_coordinator_can_reconcile_only_their_space`; `test_admission_payment_requires_same_tenant_and_applicant`; `test_canceled_admission_charge_never_schedules_activation`
- `backend/tests/payments/test_rejoin_admission_access.py`: `test_rejoining_revoked_applicant_reads_only_new_admission_charge`; `test_rejoin_web_checkout_is_new_charge_only`; `test_rejoin_money_exception_requires_live_approved_managed_pending_application`; `test_rejoin_money_exception_preserves_account_tenant_and_module_gates`; `test_reactivation_restores_ordinary_own_money_history`
- Modified existing test: backend/tests/makerspaces/test_invitation_requests.py::test_module_off_answers_400_and_bad_input_400 (renamed expectation from 404 to 400).

Parametrization includes the full 20-case join-mode x free/paid x timing matrix, vouch invalidity/expiry/recovery cases, rejoin rules and gateway settlements. No backend test pass is claimed.

## Every added frontend test (30 cases; included in the passing focused run)

- `frontend/src/features/members/AdmissionJoin.test.tsx`: `shows the %s entry mode [open, approval, invite_only, vouch, closed]`; `explains paid open activation with %s [after_activation, before_activation]`; `collects application answers before submitting`; `offers sign-in without exposing a submit action to anonymous applicants`; `keeps admission questions and actions accessible`
- `frontend/src/features/members/MemberAdmission.test.tsx`: `shows pay-before-activate with an offline path and no active-membership claim`; `provides an application number and immutable vouch identity`; `renders eligibility refusals and permits a corrected vouch retry`
- `frontend/src/features/members/MemberAreaAdmission.test.tsx`: `shows awaiting-payment and the offline debt to an applicant who is not yet a member`; `does not call admission endpoints when the membership module is off`; `allows a revoked member to reapply without offering vouching authority`
- `frontend/src/features/members/MemberInvitationAdmission.test.tsx`: `collects answers on claim and does not promise immediate activation`; `hides referral and claim actions when admissions are closed`
- `frontend/src/features/staff/MembershipAdmissionSettings.test.tsx`: `prefills %s without retained pricing [free_open, free_vouch]`; `retains the selected plan for %s and requires payment first [paid_approval, paid_invite_only]`; `lets a manager edit a recipe before saving and refreshes member state`
- `frontend/src/features/staff/MembershipAdmissionReview.test.tsx`: `shows the answer snapshot and named vouchers while preventing repeat approval`; `exposes receipt-based offline settlement only with finance recording authority`
- `frontend/src/features/staff/WalkInMemberForm.test.tsx`: `selects an active walk-in only after the borrower list refreshes`; `keeps an awaiting-payment applicant out of the handout selection`; `validates and sends staff-collected application answers for a vouch applicant`; `refuses creation in closed mode`; `keeps creation disabled when admission conditions could not be loaded`
