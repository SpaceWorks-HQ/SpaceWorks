# Lane `membership` — progress

Branch `lane/membership`, based on `dev` at `b7c2ee93`. Hard stop for new work: 06:00 IST.

## Done

- Step 1 AUDIT (00:33 IST): `00-audit.md` (cases §1–§8, combination matrix §9, decisions + drift +
  out-of-scope defects §10) and `01-plan.md` (groups G1–G9).
  **Location:** the file tool refused to write into the main checkout from this isolated worktree, so
  both live at `docs/plans/2026-10-09-membership-completeness/` INSIDE this worktree (gitignored there,
  like in main). Copy them to the main checkout's same path.

## Mid-flight

- Step 2 GAPS, group G1 (lapsed switch configurable + enforced at self-checkout and direct handout).

## Next

- G2 module gating per A7, G3 protected roles, G4 revocation consequences, G5 card re-issue after
  revoke, G6 member term visibility, G7 matrix pins, G8 console parity, G9 docs.

## Tests actually run

- Baseline (in progress): `./scripts/dev.sh test tests/makerspaces tests/member_activity
  tests/test_memberships.py tests/test_member_cards.py tests/test_p4_membership_revocation.py
  tests/test_part_l3b_memberships.py -q -p no:randomly`.
