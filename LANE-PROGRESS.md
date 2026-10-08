# Lane 7a progress — device identity

Branch `lane/7a`, based on `b7c2ee93`. Plan:
`docs/plans/2026-09-03-forward-plan/phase-7a-device-identity.md` (main checkout).

## Done
- Plan steps 2-10 implemented (module key, RBAC + 0073, models + 0001 + trigger, enrollment PoP,
  signed auth + nonce + heartbeat, route registry + checks, source-gate guard extension,
  provenance/audit, purge, export + tenant-migration catalogs, recovery reset, report coverage,
  OpenAPI + api.ts, docs: MODULES, README, SOURCE-MAP, INVARIANTS, LANDING-PAGE-FEATURES,
  device-protocol.md, self-hosting, deploy-production, env examples).
- Overview `00-overview.md` synced in the main checkout (34 modules, 9 profiles, 4 oversized files,
  7a marked BUILT).

## Mid-flight
- Final verification runs: tests/backup + tests/tenant_migration; core suites; tombstone profile.
- Then squash wip commits into one phase commit (this file kept as a separate trailing commit).

## Tests actually run (counts seen)
- Guard batch (registries, separability, env drift, module registry, operations, source gate):
  3 failed / 651 passed -> fixed (catalog digest, object-key exemption, authority matrix).
- tests/devices + source-gate device guard + contract matrix + custom roles + rbac dual read +
  object-field coverage + Lane D catalog + authority matrix: **388 passed, 18 skipped, 0 failed**.
- tests/devices/test_concurrency.py: 1 passed.
- Frontend: tsc -b ok, vitest 277 passed (64 files), vite build ok.
- manage.py check: clean; makemigrations --check: no changes; diff CLAUDE.md AGENTS.md: empty.
