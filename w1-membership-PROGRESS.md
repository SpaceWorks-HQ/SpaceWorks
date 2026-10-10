# w1-membership review handoff

## Review pass - 2026-10-11

Reviewed the root instructions, original research/owner decisions, completeness audit,
existing lane handoff, uncommitted implementation and its tests. The requested named
progress file was absent; this file now supplements `LANE-PROGRESS.md`.
Every edit remains unstaged. No database test or state-changing git command ran.

## Defects found and fixed

1. Vouch HTTP used an unsupported `field` argument to `scope_by_makerspace`, causing
   a server error. Used `makerspace_field` and scoped the applicant lookup too.
2. Revocation canceled old membership/term dues but left activate-then-charge admission
   debt payable. It now cancels only pending admission debt through the existing
   cancellation service, which audits the cancellation and preserves settled money.
3. Configured community invitation claims omitted the staff application-received
   notice. Claims now send the existing membership-family staff event.
4. The frontend imposed community questionnaires on staff invitation claims.
   Discovery now identifies staff invitations; staff claims bypass those questions
   and describe their separate approval step.
5. Review queue serializers exposed admission money to MANAGE_MEMBERS-only actors.
   They now use the existing VIEW_FINANCE-scoped bulk payment context, including
   approve/revoke responses. Applicants still see their own debt.
6. Voucher reads lacked an explicit reviewer scope. Member serializers now use
   MANAGE_MEMBERS; capability mutation responses pass their actor so authorized
   managers retain voucher accountability and delegated verifiers fail closed.
7. MembershipRequest export predicates lacked guards on new selected-plan/payment
   relationships. They now reject foreign tenant edges; an actual queryset regression
   checks both corrupt relationships and null relationships.
8. A retained join component could carry private answers into another makerspace.
   The component is keyed by the resolved tenant slug, resetting its local state.
9. Configured active-member staff attachments went through the admission activation
   path, silently leaving the old role unchanged. Existing active rows now use the
   established role-update path. Closed admissions block new/inactive attachments,
   while existing active role changes remain possible.
10. Application-export GET wrote an audit row outside the HTTP mutation gate.
    It now holds `tenant_write` through data construction and audit commit.
11. Direct settlement activation depended on an enclosing HTTP/task gate.
    The activation callback now owns a tenant write boundary, refusing a frozen
    source without losing its committed receipt; the scheduler can retry later.
12. Admission and changed join/review/walk-in schemas omitted source-gate errors.
    Their response schemas now include typed 423/503 responses.
13. Settings copy claimed only new applications were affected. It now explains that
    current conditions change while submitted answers and raised charges retain
    their snapshots.
14. Six inherited files contained CRLF, and the original handoff had damaged
    punctuation. Files are now LF-only, and handoff punctuation uses plain ASCII.

## Verification

- `python -m py_compile` succeeded on all 104 changed backend Python files.
- Static `validate_source_gate_coverage()` succeeded: 38 task declarations,
  4 webhook boundaries, 33 anonymous HTTP boundaries and 114 object mutations,
  plus authenticated HTTP, lifecycle and fan-out checks. It makes no DB connection.
- `npx.cmd tsc -b` exited 0.
- Focused `npx.cmd vitest run` passed 27 files / 102 tests, covering all member
  feature tests and staff admission settings/review, walk-in, roster and payment UI.
- `git diff --check` succeeded. The index is empty. Changed files have no CRLF/BOM
  or detected mojibake; code files stay below 300 lines except the accepted Django
  settings exception. AGENTS.md/CLAUDE.md are unchanged and byte-identical.
- Backend tests were written and syntax-checked, but NOT executed. Migration drift,
  forward/reverse migration checks and the generated OpenAPI snapshot remain pending.
- PowerShell blocks npx.ps1; npx.cmd worked. Codex doctor could not resolve usable
  sandbox home/config/provider access; the coordinator must run the mandatory gate.

## Tests added by this review

New `backend/tests/makerspaces/test_membership_admission_review.py`:

- `test_vouch_http_scopes_local_member_and_refuses_foreign_or_revoked_member`
- `test_revocation_cancels_only_unpaid_activate_then_charge_admission` (2 cases)
- `test_claimed_community_invitation_notifies_staff_of_received_application`
- `test_staff_invitation_discovery_identifies_core_claim_without_application_form`
- `test_roster_reviewer_cannot_read_admission_money_without_finance_authority`
- `test_configured_staff_attachment_still_updates_an_existing_active_role` (open/closed)
- `test_frozen_tenant_refuses_export_audit_and_direct_paid_activation`
- `test_member_capability_mutation_keeps_scoped_voucher_accountability`

Extended `backend/tests/data_export/test_membership_admission.py`:

- Added `test_application_export_queryset_excludes_foreign_plan_and_payment_edges`.
- Extended `test_admission_dataset_refuses_foreign_plan_or_request` for request edges.

Extended frontend tests:

- `MemberAreaAdmission.test.tsx`: clears private application answers when navigating
  to another makerspace.
- `MemberInvitationAdmission.test.tsx`: claims a staff invitation without community
  application answers.

## Coordinator backend test paths

Run these through the isolated test runner, then the broader related regression suites:

```text
backend/tests/makerspaces/test_membership_admission_review.py
backend/tests/makerspaces/test_membership_admission_api.py
backend/tests/makerspaces/test_membership_admission_lifecycle.py
backend/tests/makerspaces/test_membership_admission_matrix.py
backend/tests/makerspaces/test_membership_admission_vouches.py
backend/tests/makerspaces/test_invitation_requests.py
backend/tests/data_export/test_membership_admission.py
backend/tests/operations/test_membership_payment_reminders.py
backend/tests/payments/test_admission_payment_locking.py
backend/tests/payments/test_admission_settlement.py
backend/tests/payments/test_rejoin_admission_access.py
```

For `scripts/dev.sh test`, omit the leading `backend/`. Also run existing membership,
staff attachment, capability, payment, reminder/scheduler, encryption, tenant-migration
and API-client drift regressions. Recompute the combined tenant catalog SHA pin after
all lanes integrate, regenerate OpenAPI/client artifacts, and perform browser QA.

## Migrations

No migration was created or changed by the review. Existing lane migrations:

- `makerspaces/0080_membership_admission.py`: depends on
  `makerspaces.0079_staff_invitations_feature`, `payments.0019_membership_request_subject`,
  `encryption.0007_tenant_import_fence_operation`, and swappable AUTH_USER_MODEL.
- `payments/0019_membership_request_subject.py`: depends on
  `payments.0018_offline_refund_receipt`.

Listed the actual migration leaves; no extra migration number was assumed.
New models/request fields have export classification, user-FK declarations,
encryption and tenant catalog/projection/authority entries in the inherited lane.
The new task and fan-out have explicit gate_policy_tasks declarations. There is
no new object-storage writer, environment variable or module key to register.

## Every file created or modified by this review

Created:

- `w1-membership-PROGRESS.md`
- `backend/tests/makerspaces/test_membership_admission_review.py`

Modified (some were untracked files from the previous implementation):

- `LANE-PROGRESS.md`
- `backend/apps/admin_api/serializers_member_memberships.py`
- `backend/apps/admin_api/services_staff.py`
- `backend/apps/admin_api/views_member_capabilities.py`
- `backend/apps/admin_api/views_member_memberships.py`
- `backend/apps/admin_api/views_membership_admission.py`
- `backend/apps/admin_api/views_walk_in.py`
- `backend/apps/data_export/datasets.py`
- `backend/apps/makerspaces/membership_admission.py`
- `backend/apps/makerspaces/membership_admission_payments.py`
- `backend/apps/makerspaces/membership_revocation.py`
- `backend/apps/makerspaces/serializers_memberships.py`
- `backend/apps/makerspaces/views_admission.py`
- `backend/apps/makerspaces/views_invitation_requests.py`
- `backend/apps/makerspaces/views_membership_invitations.py`
- `backend/apps/makerspaces/views_memberships.py`
- `backend/apps/payments/services_checkout.py` (LF normalization only)
- `backend/apps/payments/checkout_coordination.py` (LF normalization only)
- `backend/apps/payments/checkout_provider.py` (LF normalization only)
- `backend/apps/tenant_migration/tenant_dump_authority.py` (LF normalization only)
- `backend/apps/tenant_migration/tenant_dump_authority_entries.py` (LF normalization only)
- `backend/tests/data_export/test_membership_admission.py`
- `docs/SOURCE-MAP.md`
- `docs/membership-admission.md`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberReferrals.tsx`
- `frontend/src/features/members/MemberAreaAdmission.test.tsx`
- `frontend/src/features/members/MemberInvitationAdmission.test.tsx`
- `frontend/src/features/staff/MembershipAdmissionSettings.tsx`

`LANE-PROGRESS.md` retains the inherited implementation's full file/test inventory.
`docs/SOURCE-MAP-FRONTEND.md` was already modified and remains untouched by this review.

## Skipped work, owner decisions and unrelated defects

- No outstanding owner product decision. Vouch defaults are 1 / 30 days / 3 pending;
  accountability remains flag-only as explicitly required.
- Database/migration checks and generated schema/client changes were deliberately
  left to the coordinator per lane instructions; browser QA also remains pending.
- Existing native payment grants require active membership; applicants use hosted
  checkout or offline settlement, as documented in the original handoff.
- The base tenant catalog SHA pin is RECOMPUTE; pin it after all lanes integrate.
- Outside task: ordinary hosted checkout does not share the member history
  endpoint's unrestricted-account predicate. Existing revoked-member Presence UI
  remains visible although the backend refuses the action. Neither was changed.
