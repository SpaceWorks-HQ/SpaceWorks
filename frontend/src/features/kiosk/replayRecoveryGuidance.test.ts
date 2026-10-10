import { describe, expect, it } from "vitest";
import { REPLAY_GUIDANCE, replayGuidance } from "./replayRecoveryGuidance";

describe("typed replay guidance", () => {
  it("provides an actionable path for the full server catalog", () => {
    const codes = "rate_limited invalid_command idempotency_conflict command_expired clock_skew lease_expired station_revoked session_mismatch feature_disabled module_disabled permission_revoked predecessor_missing predecessor_pending predecessor_failed evidence_missing evidence_invalid claim_in_progress unsupported_operation_version qr_revoked qr_mismatch request_state_changed loan_state_changed deposit_unsettled presence_expired membership_required waiver_required box_scan_required box_mismatch inventory_unavailable storage_unavailable server_unavailable target_missing domain_invalid".split(" ");
    expect(Object.keys(REPLAY_GUIDANCE).sort()).toEqual(codes.sort());
    for (const code of codes) expect(replayGuidance(code).length).toBeGreaterThan(20);
    expect(replayGuidance("unrecognized")).toContain("Keep this evidence");
  });
});
