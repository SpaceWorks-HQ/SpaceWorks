# Lane `membership` — progress

Branch `lane/membership`, based on `dev` at `b7c2ee93`. Hard stop for new work: 06:00 IST.

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

## Not done (see 00-audit.md §10/§11)

- Owner decisions D1–D11; frontend reason prompts, plan picker, pagination, delegated-verifier and
  claim-code surfaces; remaining BUILT-UNTESTED rows.

## Tests actually run (all `./scripts/dev.sh test … -q -p no:randomly`)

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
