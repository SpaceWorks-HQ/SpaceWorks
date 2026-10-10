# Lane `membership` — progress

Branch `lane/membership`, based on `dev` at `b7c2ee93`.

## Done

- Step 1 AUDIT: `00-audit.md` (cases §1–§8, combination matrix §9, decisions + drift + out-of-scope
  defects §10, step-2 outcome §11) and `01-plan.md`, in `docs/plans/2026-10-09-membership-completeness/`
  of the worktree AND the main checkout (gitignored in both).
- G1 `17a448b5` lapsed rule at self-checkout + direct handout; switch in the settings serializer.
- G2 `cf8c4129` A7 end to end (staff invitations module-off; community claim gated; card actions gated;
  approve-with-plan atomic).
- G3 `a741138c` protected Member role: no actions; slug survives rename.
- refactor `7fb05643` revocation split out of `membership_services` (ceiling).
- G4 `b46fbe84` revocation takes card/terms/renewals; invite-to-active refused; no delegation on revoked;
  combination-matrix tests (paid+invite-only, free+vouch, neighbours).
- G8 `c70c4cea` console approve/invite `role_id: null` bug; queue module-off; cancel invitation.
- G5 `66ab41f6` revoked card replaceable (migration `makerspaces/0073`).
- G6 `744447c8` member term visibility + notices; profile/card/directory gated on the module.
- Matrix waiver pins (M14–M16) — `test_membership_matrix_waivers.py`.

## Continuation — 2026-10-10 (unstaged, coordinator-owned commit)

- Read the main-checkout audit and plan; keep all D1–D11 stated defaults.
- Built reason/confirmation dialogs, approval plan picker, roster and queue pagination,
  member-area delegated verifier controls, and claim-code redemption. Existing staff code
  issue/revoke UI now distinguishes query errors from an empty list.
- Member waiver acceptance button now follows `waiver_acceptance_required`.
- Staff waiver form now reads the active text and can deactivate it. Member profile, directory,
  avatar and project image requests carry the member/public credentials, with visible read errors.
- Added a member-facing verification route: real member JWTs cannot call the old `/admin/` route.
  The new route reuses the existing scoped lookup and locked verification service, returns only
  membership ID/display name/verification time, and explicitly refuses claim sessions.
- Claim redemption switches to a tenant-local session view (presence, waiver, optional activity),
  without calling global account routes. Changing principal removes cached member snapshots
  without refetching them under the bounded token.
- Added backend pins for the audit's remaining enrolment, card-photo, card-print, waiver, profile,
  identity, money, retention and matrix surface rows; retained the earlier paid-invite-only and
  free-vouch matrix tests. All new backend tests remain UNEXECUTED here.
- Frontend validation: full Vitest suite **76 files / 317 tests passed**; `npx tsc -b` and
  `npm run build` passed. Python AST parsing, literal reverse-name check, `git diff --check`,
  and touched-code 300-line ceiling checks passed. These are not database test results.
- Remaining coordinator work: run the backend commands below, regenerate the schema and generated
  client, review and commit the unstaged changes. No git state-changing commands used here.
- No database tests run in this continuation; the coordinator must run every new backend test.
- No migrations or generated OpenAPI/client changes in this continuation.

## Continuation file inventory

Backend runtime, modified:
- `backend/apps/accounts/claim_routes_member.py`
- `backend/apps/admin_api/views_member_memberships.py`
- `backend/apps/makerspaces/urls.py`

Backend runtime, created:
- `backend/apps/makerspaces/member_verification_views.py`

Backend tests, modified:
- `backend/tests/accounts/test_claim_routes.py` — route matrix count and new refusal policy.
- `backend/tests/accounts/test_walk_in_claim_gaps.py` — exact claim refusal statuses, live revocation
  at an allowed route, working-password walk-in guard, locked phone marker, phone unlink.

Backend tests, created (the descriptions name the new behavioral pins):
- `backend/tests/makerspaces/test_member_card_photo_lifecycle.py` — POST/PUT MIME/staging presigns,
  consent, single promotion/replay, quota credit, foreign/missing/oversized objects, preview watermark.
- `backend/tests/makerspaces/test_member_card_remaining.py` — Letter/single PDF sizes, stable QR,
  revoked print, inactive scan, box QR refusal, custom actions, issue/name/reissue audits.
- `backend/tests/makerspaces/test_member_verification_http.py` — real JWT verify/unverify, no staff
  access, self/foreign/refused target, lost delegation, offstate, claim denial, invalid payloads,
  scoped staff waiver read/deactivate with the module off.
- `backend/tests/makerspaces/test_membership_certification_defaults.py` — revoked grant gate,
  reactivation and fixed stored expiry (D7).
- `backend/tests/makerspaces/test_membership_identity_remaining.py` — social import adoption,
  Apple accounts-off gate, phone switch rechecked after a valid challenge.
- `backend/tests/makerspaces/test_membership_lifecycle_remaining.py` — already-active request,
  throttle, inactive/restricted/suspended 403, foreign invitation role, invalid service claims,
  delegation audits, historical verification on reactivation, no implicit open-join plan.
- `backend/tests/makerspaces/test_membership_matrix_surfaces.py` — revoked request/checkout/booking/
  event/machine access, revoked presence, verified stale waiver and witnessed current event access.
- `backend/tests/makerspaces/test_membership_money_activity_remaining.py` — owned debt module-off,
  revoked owner denial, two-tenant activity isolation and true multiple-currency totals.
- `backend/tests/makerspaces/test_membership_offstate_http.py` — staff/member community HTTP 400
  matrix, card issue/detail gates, core publish/witness (no module gate).
- `backend/tests/makerspaces/test_membership_plan_remaining.py` — fail-safe renewal sweep, offline
  settlement does not open another term, plan create/PATCH and term-cancel audits.
- `backend/tests/makerspaces/test_membership_profile_remaining.py` — public identity search,
  unknown/foreign 404 parity, text bounds, image audits, GitHub command due/failed/all behavior.
- `backend/tests/makerspaces/test_membership_retention_remaining.py` — terms/plans/leads purge,
  foreign retention, report composition, archive HTTP discovery, four-edition joins.
- `backend/tests/makerspaces/test_membership_waiver_remaining.py` — superseded timestamp, duplicate
  version 400, publish/deactivate/accept audits, current-version D9, absent-waiver witness 400.

Frontend runtime, modified:
- `frontend/src/features/staff/MembersPanel.tsx`
- `frontend/src/features/staff/MemberClaimCodes.tsx`
- `frontend/src/features/staff/ImageUploader.tsx`
- `frontend/src/features/members/MemberArea.tsx`
- `frontend/src/features/members/MemberDirectory.tsx`
- `frontend/src/features/members/MemberProfilePanel.tsx`
- `frontend/src/features/members/memberProfile/ProjectEditor.tsx`

Frontend runtime, created (each has an adjacent `.test.tsx`):
- `frontend/src/features/staff/MembershipReasonDialog.tsx` — required reason, cancel/confirm/error.
- `frontend/src/features/staff/MembershipPagination.tsx` — server-backed previous/next/pending.
- `frontend/src/features/staff/MembershipPlanPicker.tsx` — optional active plan/loading/error/empty.
- `frontend/src/features/staff/MembershipWaiverPanel.tsx` — read/publish/deactivate/loading/error.
- `frontend/src/features/members/MemberVerifierPanel.tsx` — scoped verify/remove/pending/errors.
- `frontend/src/features/members/MemberClaimRedemption.tsx` — claim redemption/token/error.
- `frontend/src/features/members/MemberClaimSession.tsx` — bounded token discovery/local routes.

Additional frontend tests, created:
- `frontend/src/features/members/MemberArea.test.tsx` — waiver acceptance, verifier/module gates,
  claim-only session and principal switch without forbidden account refetches.
- `frontend/src/features/members/MemberDirectory.test.tsx` — member calls, empty/loading/list/detail errors.
- `frontend/src/features/members/MemberProfilePanel.test.tsx` — member read/write/loading/errors.
- `frontend/src/features/staff/ImageUploader.test.tsx` — member presign/attach/clear session.

Frontend tests, modified:
- `frontend/src/features/staff/MembersPanel.test.tsx` — default role, cancel reason, plan approval,
  decline/revoke reason, roster and request pagination.
- `frontend/src/features/staff/MemberClaimCodes.test.tsx` — issue/revoke secret clearing and query states.

Root modified: `LANE-PROGRESS.md` (this handoff).

## Coordinator backend validation (not run in this sandbox)

Run sequentially; each command uses the isolated runner's current worktree mount:

```bash
./scripts/dev.sh test tests/makerspaces/test_member_card_photo_lifecycle.py tests/makerspaces/test_member_card_remaining.py tests/makerspaces/test_member_verification_http.py tests/makerspaces/test_membership_certification_defaults.py tests/makerspaces/test_membership_identity_remaining.py -q -p no:randomly
./scripts/dev.sh test tests/makerspaces/test_membership_lifecycle_remaining.py tests/makerspaces/test_membership_matrix_surfaces.py tests/makerspaces/test_membership_money_activity_remaining.py tests/makerspaces/test_membership_offstate_http.py -q -p no:randomly
./scripts/dev.sh test tests/makerspaces/test_membership_plan_remaining.py tests/makerspaces/test_membership_profile_remaining.py tests/makerspaces/test_membership_retention_remaining.py tests/makerspaces/test_membership_waiver_remaining.py tests/accounts/test_claim_routes.py tests/accounts/test_walk_in_claim_gaps.py -q -p no:randomly
./scripts/dev.sh test tests/makerspaces/test_membership_matrix.py tests/makerspaces/test_membership_matrix_actors.py tests/makerspaces/test_membership_matrix_waivers.py tests/accounts/test_member_claim_code_p7.py tests/accounts/test_claim_session_contract_p7.py tests/accounts/test_claim_acceptance_p7.py -q -p no:randomly
```

The final line exercises earlier lane matrix pins (paid invite-only/free vouch etc.).
The full membership/account/card regression suites remain coordinator gates too.

## Defaults, skips and outside-scope defects

- D1–D11: all have an explicit default; all retained. No blocking owner decision. No pay-before-
  activation state, deeper vouch rules/counters/limits, first-term upfront charge, default plan,
  closed policy, revocation verification/certification reset, decline emails, client-version waiver
  binding, invite-email encryption, or OIDC/password/phone import adoption added.
- Skipped by instruction: database execution and generated OpenAPI/client regeneration.
- No new model, module key, feature key or migration. AGENTS/CLAUDE unchanged.
- Audit defects outside this lane remain: inventory scanner writes before member-card refusal;
  presence service does not check account `access_status`; GitHub sync includes revoked/module-off
  profiles; invitation-request leads queue unpaginated; invitation-request lock-order inversion;
  duplicate join replies 400 while schema also advertises 409. No unrelated fixes bundled here.

## Earlier lane validation (historical; not re-run here)

All backend commands below used `./scripts/dev.sh test … -q -p no:randomly` in the earlier lane session.

- Baseline before any change: tests/makerspaces tests/member_activity tests/test_memberships.py
  tests/test_member_cards.py tests/test_p4_membership_revocation.py tests/test_part_l3b_memberships.py →
  **364 passed**.
- G1: lapsed + plans + self-checkout + direct loans → **66 passed**.
- G2: a7 + gating + j1 + j2 + j5 + m2 + cards + plans + invitation requests → 65 passed, 1 failed (old
  "queue is 400 module-off" assertion, updated to the new contract) → a7 + gating re-run **21 passed**.
- G3: protected role + custom roles l1 + l3b → **22 passed**.
- G4: matrix + cards + j1 + m2 + plans + presence m3 → **48 passed**.
- G5: replacement + cards + matrix + tenant_migration target projection + certification extras + module
  purge → **79 passed**.
- G6: tests/member_activity → **18 passed**.
- Frontend: `npx tsc -b` clean; `npm test` **65 files / 285 tests passed**; `npm run build` OK.
- `manage.py check`: 1 environment warning (AUDIT_MAC_MASTER_KEY unset in the one-off container).
- Final chunks: see the final report (a first combined run died with a Docker "unexpected EOF" under
  memory pressure from parallel lanes and produced no results).
