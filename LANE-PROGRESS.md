# Lane `cloud` — progress

Branch `lane/cloud`, forked from `dev` at `b7c2ee93`. The brief: "online cloud services —
all conditions". Step (1) is the audit matrix. Step (2) closes every MISSING and
BUILT-UNTESTED cell.

The audit and plan are committed at `LANE-CLOUD-AUDIT/00-audit.md` and `01-plan.md`. This
worktree-isolated session was refused writes to the main checkout's gitignored
`docs/plans/`. Move both files to `docs/plans/2026-10-09-cloud-completeness/` when the lane
is squashed.

## Done

- (1) Audit and plan.

## Mid-flight

- G1: outbound fail-safe fixes. Its tests are written; the fixes are not.

## Next

- G1 through G10, in the order given in `01-plan.md`.

## Tests actually run

- `./scripts/dev.sh test tests/test_apiclient_failure_modes.py tests/test_channel_provider_failures.py tests/test_managed_quota_check_fail_open.py tests/test_notification_requeue_action.py`
  ran **before** any fix: 90 passed, 3 failed.
  - Two of the failures are the expected reproductions of the `dispatch_email` and
    `reserve_notification_quota` bugs.
  - The third was a test-side bytes/str mistake, since corrected.
