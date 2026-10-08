# LANE-PROGRESS — lane/10 (phase 10, audit explorer)

Base: `dev` at `b7c2ee93`. Plan: `docs/plans/2026-09-03-forward-plan/phase-10-audit-explorer.md`
(main checkout; gitignored). Revision record + build deviations: `reviews/stage1d-p10.md` (both copied to
the main checkout's docs/plans).

## Done (all committed)
- Step 0: plan revised — 5a taxonomy confirmed already applied; the wrong "fix `_validate_fetched()`"
  instruction removed (sinks classify instead); Files table re-counted against b7c2ee93.
- Step 7a: sink-boundary taxonomy (`AnchorTransportError` / `AnchorConfigurationError` /
  `AnchorInvalidEvidence` > `AnchorConflict`), `AnchorReadBudget`, manual budgeted S3 listing,
  preloaded-leaf `verify_batch_local`, rotation verifier no longer collapses failures.
- Step 2: fail-closed presentation catalogue (329 actions, 8 fragments) + line-free deny policy + guard.
- Step 3: `/admin/audit-logs` projected meta + 4 additive fields + validated actor/start/end filters.
- Step 4: request timeline `kind=audit` rows + `evidence_retention`.
- Steps 5/6: immutable `AuditVerificationRun` / `...Event`, migration `audit.0009` with DB triggers,
  data_export/tenant-dump/purge/admin/hidden-scope registries, digest re-blessed.
- Steps 7b/8/9: `integrity_scope`, admission/dedupe/bounds, execution + named Celery task + resolver,
  staff API (202/400/404/409/429), throttle setting + ENV_SURFACE, origin-scope routes.
- Step 1 + 10: views_reports / OperationsReports split; `audit-trail` CSV report with the four
  definition capabilities enforced everywhere; report-aware makerspace resolver.
- Steps 11/12: audit panel filters + verification UI, timeline rendering, CSV-only exports, schedulable
  filter, schedule form formats; live.ts invalidates audit keys for every kind.
- Step 13: OpenAPI + api.ts regenerated; INVARIANTS / SOURCE-MAP / PROJECT-STATUS / MODULES updated.

## Tests actually run (all green)
- `dev.sh test` anchor work + existing audit suites: 124 passed.
- `dev.sh test` pagination/timeline/runs/presentation/registry/guard/lifecycle/origin/env/apiclient
  batch: 138 passed.
- `dev.sh test` verification API/task + reports (new + existing report suites) + presentation: 123 passed.
- Frontend: `npx tsc -b` clean; `npm test` 67 files / 285 tests passed; `npm run build` OK.
- In flight at time of writing: broad backend batch (data_export, operations, makerspaces, separability,
  modules, all audit suites, admin/lifecycle) and `tests/tenant_migration`; plus the last added tests
  (rotation, purge, budget, leaf bound). See final report for their counts.

## Not done / next
- `tests/backup` and the full repository suite were not run (time).
- Known limitation: genesis-membership check in the anchor phase is unbounded (see stage1d §3).
