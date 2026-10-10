# Lane w1-rbac progress

## Completed

- Added MANAGE_MEMBERS, VIEW_FINANCE and RECORD_PAYMENT with four protected defaults unchanged.
- Added Membership Coordinator, Treasurer and Front-desk cashier custom-role presets.
- Narrowed roster, requests, community invitations, verification, presence, plan reads/term assignment and cards.
- Kept settings, staff delegation, plan definitions/prices and waiver publishing on makerspace administration.
- Separated full finance reads from cashier counter queries and audited offline receipt/refund recording.
- Preserved existing scoped subject authority for cash work, debt waivers and provider refunds.
- Added additive, idempotent role/organization-grant backfill; no dynamic manage_makerspace implication.
- Split role services into explicit authority/CRUD/assignment re-exports and split the source map.
- Left all changes unstaged. No git state-changing commands were run.

## Review pass

Defects found and fixed:

1. Finance readers could open Reports but React hid payment reconciliation behind manage_makerspace. The report panel now uses view_finance, and unauthorized hardware summaries are hidden instead of presenting zero metrics.
2. The roster hid money and payment controls behind settings authority. Finance visibility, cash recording and debt waiving now use independent permission props; read-only finance cannot mutate payments.
3. The roster hid verification/terms/witness controls on staff rows from coordinators. Those controls now remain available while role changes/revocation remain restricted; staff-invitation approval/cancellation controls are hidden.
4. A coordinator could approve an existing staff invitation with a community role. The locked approval service now refuses staff invitations without makerspace administration, preserving both the invitation and its intended role.
5. Delegated verifier lookups bypassed RBAC hidden-space filtering. Both the view lookup and locked service now scope delegate memberships through RBAC; hidden superadmins cannot use a local can_verify membership as a bypass.
6. Presence queried a tenant directly after a boolean permission check. Both the makerspace lookup and session query now use scope_by_action, including foreign/hidden-space refusal.
7. Capability delegation bypassed the membership-off gate. The endpoint returns 400 and verification/capability services recheck the module under the makerspace lock.
8. Plan edits required both roster and settings grants, preventing independent settings authority. Definition writes now scope by manage_makerspace; plan reads/term assignment retain manage_members.
9. Membership-plan writes committed before their audit entry. Audit writes now share the mutation transaction, with a locked module recheck, so audit failure rolls back create/update.
10. OpenAPI omitted card 400/401 errors and inaccurately described plan/waiver writes and delegated verification. These schemas now describe the actual gates and typed errors.
11. The new role-authority/assignment modules were absent from the tenant-migration authority scan. They are now registered with a regression guard; pinned accounts/rbac.py bodies remain unchanged.
12. Endpoint matrix plan fixtures omitted interval, which would break approvals/term creation before checking RBAC. Fixtures now use monthly plans. Module-off capability coverage and review-specific regression tests were added.
13. Removed duplicate source-map and created-file entries from the previous handoff.

## Validation performed

- python -m py_compile completed for every touched backend Python file (36 files).
- npx.cmd tsc -b completed successfully. PowerShell blocks npx.ps1, so the equivalent Windows command shim was used.
- Focused Vitest run: 9 files, 34 tests passed. After the final frontend adjustment, the two review test files were rerun: 5 tests passed.
- git diff --check, touched-file LF/UTF-8/mojibake and 300-line checks completed successfully.
- AGENTS.md and CLAUDE.md remain byte-identical and unchanged; accounts/rbac.py remains byte-identical to HEAD.
- No database tests were run; no Django/PostgreSQL behaviour is reported as passing.
- codex doctor was rechecked: missing configuration/home and unreachable provider HTTP endpoints still block a separate CLI review gate.

## Remaining / coordinator validation

- Run the backend tests listed below with the isolated PostgreSQL runner.
- Also run existing membership lifecycle/plans, role CRUD/custom-role, payments reconciliation/refunds, organization authority/reports, machine scoping and tenant-servability/tenant-migration authority guards.
- Regenerate frontend/openapi-schema.json and frontend/src/generated/api.ts centrally and validate OpenAPI.
- Apply the migration before exposing new action gates to existing deployments.
- Coordinator review/QA and committing remain with the coordinator/owner.

## Migration

- backend/apps/makerspaces/migrations/0077_member_finance_actions.py
- Dependencies: makerspaces.0076_station_operator_leases and organizations.0003_organization_presentation_and_governance; actual directories/leaves inspected.
- Data-only additive backfill; reverse is no-op to preserve later administrator edits. No additional review-pass migration.

## Backend tests for the coordinator

- `backend/tests/makerspaces/test_rbac_f6_backfill.py`
  - `test_backfill_is_additive_idempotent_and_covers_custom_admin_roles`
  - `test_new_and_legacy_space_manager_keep_all_three_actions`
  - `test_role_editor_catalog_exposes_plain_descriptions_for_new_actions`
  - `test_organization_admin_backfill_preserves_actions_without_widening_reach`
- `backend/tests/makerspaces/test_rbac_f6_cards.py`
  - `test_manage_members_implies_every_card_operation`
  - `test_member_verification_route_accepts_manage_members`
- `backend/tests/makerspaces/test_rbac_f6_members.py`
  - `test_member_endpoint_matrix`
  - `test_member_module_off_is_400`
  - `test_coordinator_cannot_manage_staff_settings_plan_prices_or_waiver_text`
  - `test_roster_does_not_disclose_money_to_members_only_role`
- `backend/tests/makerspaces/test_rbac_f6_review.py`
  - `test_coordinator_cannot_downgrade_or_cancel_a_staff_invitation`
  - `test_plan_definition_authority_is_independent_of_roster_grants`
  - `test_plan_definition_and_audit_roll_back_together`
  - `test_coordinator_can_verify_staff_without_changing_their_role`
  - `test_presence_roster_only_lists_the_authorized_space`
  - `test_hidden_superadmin_cannot_use_a_delegated_verifier_membership`
  - `test_verification_services_recheck_the_locked_module_gate`
- `backend/tests/payments/test_rbac_f6_finance.py`
  - `test_finance_endpoint_matrix`
  - `test_read_only_finance_cannot_record_correct_refund_or_waive`
  - `test_cashier_has_counter_rows_but_no_ledger_reports_waives_or_provider_refunds`
  - `test_cash_work_and_finance_reads_survive_payments_module_off`
  - `test_record_authority_crosses_subjects_without_conferring_machine_authority`
- `backend/tests/tenant_migration/test_authority_guard.py`
  - `test_locked_role_authority_modules_remain_in_the_scan`

Shared fixtures: `backend/tests/rbac_f6_helpers.py`. Existing matrix tests exercise each delegated endpoint with missing, foreign, Inventory Manager and hidden-superadmin authority.

## Frontend tests

- `frontend/src/features/staff/MembersF6.test.tsx`
- `frontend/src/features/staff/PaymentsF6.test.tsx`
- `frontend/src/features/staff/panels/OperationsReportsF6.test.tsx`
- `frontend/src/features/staff/panels/RoleEditorF6.test.tsx`
- `frontend/src/features/staff/rbacF6.test.ts`
- `frontend/src/features/staff/PaymentOfflineRefund.test.tsx`
- `frontend/src/features/staff/PaymentsPanel.test.tsx`

The new review files cover coordinator staff-row controls, read-only versus recording finance, staff invitation controls, and payment report visibility without hardware queries.

## Skipped / decisions / outside observations

- Database execution and separate CLI review are infrastructure-blocked; they were not claimed as passing.
- Generated frontend API/schema files were intentionally left for the coordinator.
- No owner product decisions needed; research defaults keep plan pricing/settings/staff administration and waives/provider refunds on their existing authority.
- No new model/field, feature/module key, env var, background task, fan-out or object writer was introduced; no additional export/catalog/projection/FK, gate_policy_* or environment-reference entries are required. Existing grant JSON is already classified/projected, and the authority scan now covers the new modules.
- Outside F6: the existing scan-only member-card panel still renders issue/print/template mutation controls even though the backend requires manage_member_cards. This remains unchanged; F6 coordinators hold the managing action through implication.

## Created files

- `LANE-PROGRESS.md`
- `backend/apps/makerspaces/migrations/0077_member_finance_actions.py`
- `backend/apps/makerspaces/role_assignments.py`
- `backend/apps/makerspaces/role_authority.py`
- `backend/apps/makerspaces/role_crud.py`
- `backend/tests/makerspaces/test_rbac_f6_backfill.py`
- `backend/tests/makerspaces/test_rbac_f6_cards.py`
- `backend/tests/makerspaces/test_rbac_f6_members.py`
- `backend/tests/makerspaces/test_rbac_f6_review.py`
- `backend/tests/payments/test_rbac_f6_finance.py`
- `backend/tests/rbac_f6_helpers.py`
- `docs/RBAC-MEMBERS-FINANCE.md`
- `docs/SOURCE-MAP-FRONTEND.md`
- `frontend/src/features/staff/MembersF6.test.tsx`
- `frontend/src/features/staff/PaymentsF6.test.tsx`
- `frontend/src/features/staff/panels/OperationsReportsF6.test.tsx`
- `frontend/src/features/staff/panels/RoleEditorF6.test.tsx`
- `frontend/src/features/staff/paymentAccess.ts`
- `frontend/src/features/staff/rbacF6.test.ts`

## Modified files

- `backend/apps/accounts/rbac_actions.py`
- `backend/apps/admin_api/views_invitation_requests.py`
- `backend/apps/admin_api/views_member_capabilities.py`
- `backend/apps/admin_api/views_member_memberships.py`
- `backend/apps/admin_api/views_membership_plans.py`
- `backend/apps/admin_api/views_memberships.py`
- `backend/apps/admin_api/views_roles.py`
- `backend/apps/integrations/staff_notifications.py`
- `backend/apps/makerspaces/member_card_admin_views.py`
- `backend/apps/makerspaces/membership_revocation.py`
- `backend/apps/makerspaces/membership_services.py`
- `backend/apps/makerspaces/membership_verification.py`
- `backend/apps/makerspaces/role_services.py`
- `backend/apps/makerspaces/roles.py`
- `backend/apps/makerspaces/waiver_services.py`
- `backend/apps/operations/org_report_scope.py`
- `backend/apps/operations/report_definitions_existing.py`
- `backend/apps/payments/reconciliation.py`
- `backend/apps/payments/reconciliation_authority.py`
- `backend/apps/payments/serializers_reconciliation.py`
- `backend/apps/payments/services_refunds_offline.py`
- `backend/apps/payments/views_reconciliation.py`
- `backend/apps/payments/views_refunds_offline.py`
- `backend/apps/presence/views.py`
- `backend/apps/tenant_migration/authority_guards.py`
- `backend/tests/tenant_migration/test_authority_guard.py`
- `docs/SOURCE-MAP.md`
- `frontend/src/features/staff/MembersPanel.tsx`
- `frontend/src/features/staff/PaymentOfflineRefund.test.tsx`
- `frontend/src/features/staff/PaymentReconcileActions.tsx`
- `frontend/src/features/staff/PaymentsPanel.test.tsx`
- `frontend/src/features/staff/PaymentsPanel.tsx`
- `frontend/src/features/staff/StaffTabContent.tsx`
- `frontend/src/features/staff/panels/OperationsReports.tsx`
- `frontend/src/features/staff/panels/RoleEditor.tsx`
- `frontend/src/features/staff/paymentsApi.ts`
- `frontend/src/features/staff/staffAccess.ts`
