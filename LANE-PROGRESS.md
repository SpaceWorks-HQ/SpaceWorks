# LANE-PROGRESS — lane/10 (phase 10, audit explorer)

Base: `dev` at `b7c2ee93`. Plan: `docs/plans/2026-09-03-forward-plan/phase-10-audit-explorer.md`
(main checkout; gitignored). Revision record + build deviations: `reviews/stage1d-p10.md` (both copied to
the main checkout's docs/plans).

## Previously completed (committed lane history)
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

## Previously recorded test runs (before this completion pass)
- `dev.sh test` anchor work + existing audit suites: 124 passed.
- `dev.sh test` pagination/timeline/runs/presentation/registry/guard/lifecycle/origin/env/apiclient
  batch: 138 passed.
- `dev.sh test` verification API/task + reports (new + existing report suites) + presentation: 123 passed.
- Frontend: `npx tsc -b` clean; `npm test` 67 files / 285 tests passed; `npm run build` OK.
- `dev.sh test` last-added tests (rotation, purge, budget, leaf bound) + lifecycle: 40 passed.
- `dev.sh test tests/tenant_migration`: 823 passed, 2 xfailed.
- Broad batch (data_export, operations, makerspaces, ...): reached 51% all green, then the Docker VM ran
  out of memory (`Errno 12 Cannot allocate memory`, many lanes' stacks at once) and the run died; the
  same incident turned a concurrent `tests/backup` run into 398 identical OSError errors (345 passed,
  27 xfailed, 0 failed). Both were re-queued sequentially — see the final report for the rerun counts.

## Completion pass — 2026-10-10 (all changes unstaged)
- Fixed stage1d §3: staff anchor verification passes the existing 50,000 expanded-work cap into
  genesis verification. Oversized manifests stop before signature work/network I/O; current genesis
  membership loads only manifest IDs plus un-MAC'd rows, with SQL `LIMIT cap + 1`. Exhaustion preserves
  local aggregates and terminates `INCOMPLETE/verification_bounds_exceeded` without retries.
- Closed another plan gap: the scoped anchor phase no longer rebuilds batch envelopes through one
  leaf/key query per batch. Fetched envelopes must verify with local stored signatures/public keys and
  match signed local coordinates. Selected local membership still uses the phase-one bulk load;
  unselected batches receive chain/anchor coverage without claiming local membership for their rows.
- Verification OpenAPI now documents the actual paginated list envelope, page parameter, field-level
  validation errors, typed refusal bodies and authentication/permission/not-found/throttle bodies.
- Verification UI follows the returned status URL, blocks repeat submission before the first status
  response, shows status errors with a retry, enumerates unavailable chain coverage, and clears an old
  verdict/poller when filters or makerspace change. INCOMPLETE can never say fully verified.
- Updated audit invariants and source map. No new route, model, migration, module or feature key.

### Tests added/expanded for the coordinator
- NEW `backend/tests/test_audit_genesis_bounds.py` (9 cases): oversized manifest before queries;
  SQL-limited legacy rows before hashing; exact cap with later MAC'd history/other tenants; undeclared
  legacy detection; changed/missing manifest rows; task bounds outcome/no retry/local aggregates/audit
  event; exact-cap external success; post-admission legacy growth.
- NEW `backend/tests/test_audit_scope_anchors.py` (10 cases): complete local+anchor query count constant
  from one to four batches; unselected batch checks without rebuilding envelopes; root/signature/key/
  leaf/count/extra-field tampering; valid query-free envelope; rotated protocol-2 envelope.
- NEW `backend/tests/test_audit_verification_schema.py`: create/list/detail request, response, security,
  error and pagination schema contract.
- NEW `frontend/src/features/staff/panels/AuditVerificationStatus.test.tsx` (11 cases): full POST snapshot,
  returned URL, pending detail response, QUEUED/RUNNING/RETRYING polling, every terminal stop, unmount,
  admission/status errors and retry, coverage gaps, withheld diagnostics, conservative verdicts.
- EXPANDED `AuditLog.test.tsx`: actual page-two reset, filter/tenant verdict reset, API errors.
- EXPANDED `LoanTimeline.test.tsx`: expiring/truncated/order, loading/empty/error, custody open/hide and
  quantity display (existing audit projection/expired/null/no-photo-link case retained).

### Validation in this completion pass
- `npm.cmd test -- --configLoader runner --maxWorkers=2`: **68 files, 302 tests passed**.
- Focused audit/timeline/verification/export/schedule/live run: **6 files, 37 tests passed**.
- `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json`: passed.
- `node node_modules/vite/bin/vite.js build --configLoader runner`: passed.
- Python AST syntax parsing, `git diff --check`, touched production files below 300 lines, and
  byte-identical `AGENTS.md`/`CLAUDE.md`: passed.
- **No backend tests executed here.** This sandbox has no Django, DRF, drf-spectacular or pytest installed
  and cannot reach Docker/Postgres. The older test counts above are lane history, not this pass's results.

### Remaining coordinator work
Run the focused backend regression suite from this worktree (no concurrent pytest process):

```bash
./scripts/dev.sh test -q -p no:randomly tests/test_audit_genesis_bounds.py tests/test_audit_scope_anchors.py tests/test_audit_verification_schema.py tests/test_audit_verification_task.py tests/test_audit_verification_api.py tests/test_audit_verification_runs.py tests/test_audit_anchor_sinks.py tests/test_audit_pagination.py tests/test_audit_presentation.py tests/test_loan_timeline.py tests/operations/test_audit_trail_report.py tests/test_audit_batches.py tests/test_audit_batch_tampering.py tests/test_audit_signing_key_rotation.py
```

- Run the remaining existing audit/signing-key/report-provenance suites and the full repository harness;
  `tests/backup` and the full suite remain unverified from the earlier lane run as well.
- Regenerate `frontend/openapi-schema.json` and `frontend/src/generated/api.ts` after schema validation;
  deliberately untouched here per coordinator instructions.
- Review and commit the unstaged changes. No owner product decisions or feature work skipped.
