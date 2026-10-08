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
- `77693a58` step 6 regression tests; `d5cae275` dynamic seven-consumer proof, check/PATCH tests.

## Not done
- `docs/plans/.../phase-2-browser-and-a11y-gates.md` and `ev_evidence_retention.md` notices:
  gitignored, outside this worktree, writes refused by the harness.
- Full serial suite and full `tests/backup` + `tests/tenant_migration` (time).

## Tests actually run (all `./scripts/dev.sh test ... -p no:randomly`)
- run1 (12 files): 420 passed, 4 failed -> all 4 fixed.
- run2 (evidence, test_evidence, registry/source-gate guards, scheduler, reference registry,
  portable audit refs): 269 passed, 0 failed.
- run3: aborted by environment (OSError ENOMEM at collection).
- run4 (step-6 batch, 12 paths): 178 passed, 0 failed.
- run5 (17 paths: consumers, Lane D catalog/projection/d8, env drift, travel guard, events
  programme registry + round trips, report rollups, module registry, test_evidence): 463 passed.
- run6 (tests/evidence, tests/data_export, tests/hardware_requests, tests/operations, handout/
  asset/monitoring files): 678 passed, 0 failed.
- run7 (`tests/backup tests/tenant_migration`): ~26% (all passing, 2 xfail) when the Docker
  container died at 04:45 ("error waiting for container: unexpected EOF", exit 125) — environment.
- run8 (`tests/tenant_migration` alone): 511 passed, 2 xfailed, then OSError ENOMEM on directory
  walks for the remaining 322 tests (2 "failed" + 320 errors, all the same ENOMEM) — environment:
  the shared 8 GB Docker VM was running ~52 containers for the parallel lanes.
- run9 (12 tenant_migration files): ENOMEM at collection.
- frontend: `npx tsc -b` clean; `npm run build` ok; `vitest run src/features/staff` 197 passed;
  full `npm test` 278 passed / 1-2 failed in `MemberAreaArchivedLink.test.tsx` under load — the
  file passes 2/2 when run alone; not touched by this lane (flaky timing).
- `manage.py check` ok (only the pre-existing audit.W001); `makemigrations --check` no changes;
  `git diff --check` clean; `diff CLAUDE.md AGENTS.md` empty.
