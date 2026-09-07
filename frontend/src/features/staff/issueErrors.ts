import { StructuredApiError } from "../../lib/api";

// `apps/hardware_requests/exceptions.py` maps `DepositRequired` to 409 `deposit_required`.
// The gate runs before the QR/evidence Hard Rules, so this is the FIRST thing a handover
// hits when `loan_deposit_blocks_issue` is on -- it deserves a sentence that says what to do,
// not the generic "Action failed".
export const DEPOSIT_REQUIRED_MESSAGE =
  "The loan deposit for this request has not been paid. Issue is refused until the deposit is settled: collect it or mark it paid in Payments, then retry the issue.";

export function issueErrorMessage(error: unknown, fallback = "Action failed.") {
  if (error instanceof StructuredApiError && error.code === "deposit_required") {
    return DEPOSIT_REQUIRED_MESSAGE;
  }
  return error instanceof Error ? error.message : fallback;
}
