# Lane 11 progress — phase 11 abandoned evidence-upload cleanup

Branch `lane/11` off `dev` `b7c2ee93`. Plan: main checkout
`docs/plans/2026-09-03-forward-plan/phase-11-evidence-retention-mechanism-b.md`.

## Done (committed)
- Step 0: could NOT edit the plan file — the harness forbids writes outside this worktree.
  The exact replacements are listed in the final report.
- Step 1 (registry split): already done on dev; skipped as instructed.
- `4270643f` split `data_export/guards.py` (was at 300) before adding to it.
- `30df4ffe` step 2: schema, migrations (hardware_requests 0025, evidence 0007), consumption marker,
  seven consumers, presign views, purge order, settings/env/compose, registries, digest.
- `7a170a80` steps 3-4: policy/preview API, MANAGE_MAKERSPACE, UI move + section, CLEANING
  refusals, receipt key reservation, audit provenance, OpenAPI + api.ts.
- `8eb51692` step 5: cleanup sweep, state machine, reconciliation, task/beat/runner, gate policy.
- `904396d6` docs wording (CLAUDE/AGENTS byte-identical, INVARIANTS, README, ...).
- step 6 regression tests (this commit): public self-checkout PROTECT, backup/tenant CLEANING,
  portable audit provenance, registry pins, scheduler, managed limits, lifecycle purge receipts.

## Next
- Run the step-6 focused batch (run3 died with ENOMEM while Docker was under load), fix reds.
- Then broader suites (tests/backup, tests/tenant_migration, hardware_requests flows) if time.

## Tests actually run
- run1 (12 files): 420 passed, 4 failed -> all 4 fixed (expected-dict, credential screen,
  task registry timing, in_atomic_block test).
- run2 (tests/evidence, test_evidence, registry guards, source-gate guards, scheduled tasks,
  reference registry, portable audit refs): 269 passed, 0 failed.
- frontend: `npx tsc -b` clean; `vitest run src/features/staff` 197 passed; full `npm test`
  278 passed, 1-2 failed in `src/features/members/MemberAreaArchivedLink.test.tsx` (not touched
  by this lane; still investigating whether pre-existing).
- run3 (step-6 batch): aborted — OSError ENOMEM during collection (environment).
