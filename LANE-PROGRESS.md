# Lane `membership` — progress

Branch `lane/membership`, based on `dev` at `b7c2ee93`. Hard stop for new work: 06:00 IST.

## Done

- Step 1 AUDIT: `00-audit.md` (cases §1–§8, combination matrix §9, decisions + drift + out-of-scope
  defects §10) and `01-plan.md` (groups G1–G9), in `docs/plans/2026-10-09-membership-completeness/` of
  both the worktree and the main checkout (gitignored in both).
- G1 `17a448b5` lapsed rule enforced at self-checkout + direct handout, switch in the settings serializer.
- G2 `cf8c4129` A7 end to end (staff invitations module-off; community claim gated; card actions gated;
  approve-with-plan atomic).
- G3 `a741138c` protected Member role: no actions, slug survives rename.
- refactor `7fb05643` revocation split out of `membership_services` (ceiling).
- G4 `b46fbe84` revocation takes card/terms/renewals; invite-to-active refused; no delegation on revoked;
  combination-matrix tests (paid+invite-only, free+vouch, and neighbours).

## Mid-flight

- G8 frontend: MembersPanel posts `role_id: null` (approve/invite), queue hidden module-off.

## Next (if time before 06:00)

- G5 card re-issue after revoke (OneToOne → FK + partial unique), G6 member term visibility, remaining
  matrix pins (M14–M16, M22–M24, M26), docs drift (purge paragraph).

## Tests actually run (all `./scripts/dev.sh test … -q -p no:randomly`)

- Baseline before any change: tests/makerspaces tests/member_activity tests/test_memberships.py
  tests/test_member_cards.py tests/test_p4_membership_revocation.py tests/test_part_l3b_memberships.py →
  **364 passed**.
- G1: lapsed + plans + self-checkout + direct loans → **66 passed**.
- G2: a7 + gating + j1 + j2 + j5 + m2 + member cards + plans + invitation requests → 65 passed, 1 failed
  (the old "queue is 400 module-off" assertion, updated to the new contract) → re-run a7 + gating
  **21 passed**.
- G3: protected role + custom roles l1 + l3b → **22 passed**.
- G4: matrix + member cards + j1 + m2 + plans + presence m3 → **48 passed**.
