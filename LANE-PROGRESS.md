# LANE payments — progress

Branch `lane/payments` off `dev` @ b7c2ee93. Owner checkpoint: stop new work 06:00 IST.

## Done
- Step 1 AUDIT: `docs/plans/2026-10-09-payments-completeness/00-audit.md` + `01-plan.md` (gitignored,
  in this worktree; the coordinator copies them to the main checkout).
- G0 `scripts/dev.sh` passes `TOMBSTONED_APPS` through (58afc706).
- G1 tests for built-but-untested paths (66363de2).
- G2 expired checkout no longer returns the dead link; Razorpay links visible (88a4ab64).
- G3 native intent refuses non-Stripe sources before any provider call (ee26b742).
- G4 ISO 4217 minor units everywhere money leaves (9e026716).
- G5/G6/G7 (WIP e28f8a98): purge deletes refunds first; staff `settlement` + member refunds;
  OpenAPI 401/409/400 gaps; machine-service waive answers 409 on terminal.
- G8 frontend (0821b49a): receipts column, Correct receipt, pending-only actions, subject filter,
  member refunds; OpenAPI + api.ts regenerated.
- G5 follow-up: `machines/service_lifecycle.delete_for_makerspace` also deleted Payments with
  PROTECTed refunds — fixed (uncommitted until its test run returns).

## In flight
- Final test sweep.

## Tests actually run (all via ./scripts/dev.sh test, isolated infra)
- baseline: tests/payments tests/modules/test_offstate_money.py tests/member_activity → 222 passed.
- G1 files + tests/tenant_migration/test_source_preflight.py → 32 passed.
- G2 + 8 neighbouring payment files → 91 passed.
- G3/G4 + mobile/refunds/connect/razorpay/claim → all passed (61 dots, 0 F); G3/G4 files alone 13 passed.
- WIP group (purge/receipts/ms-routes/reconciliation/borrower/purged-machine/lifecycle/perf) →
  29 passed, 1 failed (purge-with-refund: second PROTECT path in machines.service_lifecycle → fixed).
- frontend: `npx tsc -b` clean; vitest payments + members → 41 passed.
