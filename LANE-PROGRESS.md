# Lane 11 progress — phase 11 abandoned evidence-upload cleanup

Branch `lane/11` off `dev` `b7c2ee93`. Plan: main checkout
`docs/plans/2026-09-03-forward-plan/phase-11-evidence-retention-mechanism-b.md`.

## Done
- Step 0: could NOT edit the plan file — the harness forbids writes outside this worktree.
  The exact replacements are listed in the final report.
- Step 1 (registry split): already done on dev; skipped as instructed.
- Step 2 (schema/consumption/rails): models, hardware_requests 0025, evidence 0007 (photo
  guard replacement, receipt triggers, key-reservation triggers), `consumption.py`,
  seven `mark_consumed` calls, two UNCONSUMED presign views, purge sidecar order,
  settings/env/compose/settings_policy/checks, data-export + Lane D registries, digest.
- Step 3 (API): partial PATCH, MANAGE_MAKERSPACE, extended payload/preview.
- Step 4 (safety): CLEANING refusal (backup x2, tenant export, detail API 409, admin,
  recompute_storage), receipt key COORDINATION_ONLY + legacy closure skip,
  choose_target_key reservation, audit meta/target declarations, cleaned-target provenance.
- Step 5 (cleanup): `abandoned_upload_cleanup.py`, `abandoned_upload_state.py`,
  `abandoned_upload_reconciliation.py`, task, beat + run_scheduled_tasks, gate_policy,
  storage_key_collectors receipt keys, report-rollup lookback constant.

## Mid-flight / next
- Tests: see below. Frontend panel move + UI copy + OpenAPI regen; docs wording.

## Tests actually run
- (filled in as runs complete)
