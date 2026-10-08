# LANE payments — progress

Branch `lane/payments` off `dev` @ b7c2ee93. Owner checkpoint: stop new work 06:00 IST.

## Done
- Step 1 AUDIT written (gitignored, in THIS worktree because the harness refuses writes to the
  shared checkout): `docs/plans/2026-10-09-payments-completeness/00-audit.md` and `01-plan.md`.
  Copy both to the main checkout's `docs/plans/2026-10-09-payments-completeness/`.
- G0 `scripts/dev.sh` passes `TOMBSTONED_APPS` through (58afc706).
- G1 tests for built-but-untested paths: ManualSettlement ledger, provider claim, edge conditions,
  preflight native-intent arm.

## In flight
- G2..G8 per `01-plan.md`.

## Tests actually run
- baseline before any change: `./scripts/dev.sh test tests/payments tests/modules/test_offstate_money.py tests/member_activity -q -p no:randomly` → 222 passed.
- G1: `./scripts/dev.sh test tests/payments/test_manual_settlement_ledger.py tests/payments/test_provider_claim.py tests/payments/test_payment_edge_conditions.py tests/tenant_migration/test_source_preflight.py` → 32 passed.
