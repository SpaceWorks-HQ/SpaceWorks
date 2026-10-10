# Research Wave 0 — inventory and loans

Branch/lane: `research/w0-loans`. Changes are unstaged; no state-changing git commands were run.

## Completed

- D6: reviewed returns and direct-handout returns already share the request-status finalizer;
  self-checkout returns now use it too. The finalizer schedules `loan_payments.on_request_closed`
  after commit only on terminal returns. Removed the staff-only hook to avoid duplicate callbacks.
- The existing seam records a late-fee debt before attempting an optional online checkout,
  cancels uncollected deposits, preserves paid deposits, and catches payment failures.
  Default fee calculation now uses persisted `closed_at`, avoiding additional days from delayed work.
- Split the near-ceiling self-checkout workflow into issue, return and evidence siblings behind
  its explicit compatibility barrel. Updated the source map. The coordinator can commit the
  extraction separately if required; this lane is forbidden to commit.
- D13: removed all three claims that Telegram can accept/reject requests. Decisions are in
  the staff console or `/control/`, and Telegram sends outbound alerts without decision buttons.
  Split the over-ceiling landing-page document into feature inventory and positioning companions.
- Added D6 regression tests and a D7 boundary test. No models, migrations, routes, capability keys,
  module keys or generated frontend files changed. Existing return schemas still describe the
  unchanged request/response/error contracts.

## Blocked / owner decision

- D7 is deliberately NOT implemented. `HardwareRequest.Status` has no cancelled/expired state;
  `reject_request` only accepts pending approval. The research's owner decision D1 explicitly
  identifies cancellation/expiry as new state-machine edges. Approve terminal states and their
  accepted-but-not-issued edges (or explicitly approve reuse of rejection), plus who may cancel
  and the expiry policy, before implementing reservation release. No reservation-only release
  was added because it would leave an accepted request whose stock was no longer reserved.
- No cancellation/expiry migration or desired-release tests can be written against an unapproved
  contract. The D7 boundary test verifies existing accepted reservations cannot be released by
  incorrectly invoking pending-request rejection; it does not claim to fix D7.

## Tests added — coordinator must run

`backend/tests/hardware_requests/test_return_charge_surfaces.py` (each test covers self-checkout
and direct handout; additional parametrization covers timing, switches and deposit status):

- `test_return_fee_respects_grace_rounding_cap_and_no_rail`
- `test_return_cancels_only_uncollected_deposit`
- `test_return_respects_charge_switches`
- `test_checkout_failure_preserves_fee_and_return`
- `test_charge_recording_failure_does_not_block_return`
- `test_return_rollback_does_not_charge`

`backend/tests/hardware_requests/test_return_charge_completion.py`:

- `test_partial_return_waits_until_all_units_are_resolved`
- `test_delayed_close_callback_uses_recorded_return_time`

`backend/tests/hardware_requests/test_accepted_reservation_boundary.py`:

- `test_accepted_request_cannot_be_rejected_to_release_stock`

Suggested isolated coordinator run:

```bash
./scripts/dev.sh test tests/hardware_requests/test_return_charge_surfaces.py tests/hardware_requests/test_return_charge_completion.py tests/hardware_requests/test_accepted_reservation_boundary.py tests/hardware_requests/test_loan_payments.py tests/test_public_self_checkout.py tests/test_public_self_checkout_hardening.py tests/test_admin_direct_loans.py tests/test_return_outcomes.py tests/test_return_integrity.py
```

No database tests were executed: this sandbox cannot reach Docker/Postgres, and the lane instructions
forbid running them. Python AST syntax checks and `git diff --check` completed without errors.
Static checks also verified unchanged extracted checkout/evidence/active-QR function bodies,
the preserved barrel exports, the 300-line ceiling for every touched file, and AGENTS/CLAUDE identity.
`codex doctor` could not load its configuration/home and could not reach the inference endpoint;
the external CLI review gates are unavailable and remain coordinator work, as does final QA.

## Files created or modified

- Modified `backend/apps/hardware_requests/loan_payments.py`
- Modified `backend/apps/hardware_requests/return_helpers.py`
- Modified `backend/apps/hardware_requests/return_workflow.py`
- Modified `backend/apps/hardware_requests/self_checkout_workflow.py`
- Created `backend/apps/hardware_requests/self_checkout_issue.py`
- Created `backend/apps/hardware_requests/self_checkout_returns.py`
- Created `backend/apps/hardware_requests/self_checkout_evidence.py`
- Created `backend/tests/hardware_requests/test_return_charge_surfaces.py`
- Created `backend/tests/hardware_requests/test_return_charge_completion.py`
- Created `backend/tests/hardware_requests/test_accepted_reservation_boundary.py`
- Modified `docs/LANDING-PAGE-FEATURES.md`
- Created `docs/LANDING-PAGE-POSITIONING.md`
- Modified `docs/SOURCE-MAP.md`
- Created `LANE-PROGRESS.md`

## Outside-task defects noticed / skipped

- The landing-page document also advertises reactive maintenance work orders; the index assigns
  that D13 wording to the machines lane, so it was preserved during this lane's document split.
- The landing-page payments copy still describes Payments as default-on and implies losing the
  module removes the ledger; repository rules say the online rail is opt-in and the ledger is core.
  This separate marketing drift was not corrected here.
- Self-checkout/direct-handout issuance still does not automatically raise deposits or apply the
  reviewed-loan blocking-deposit gate. The task authorizes fixing closure handling; the research's
  owner decision D4 discusses charging on these issuance paths. No new issue-time policy was added.
- Damage/loss charges and offline paid-deposit refunds are separate policy/features (research D5
  and index D14), outside this task. Paid deposits retain the existing staff-refund behavior.
