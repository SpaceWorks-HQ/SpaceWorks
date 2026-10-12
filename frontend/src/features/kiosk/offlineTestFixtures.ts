import type { KioskBootstrap, KioskLease, KioskWorkPackage } from "./kioskApi";
import type { ReplayEnvelope, ReplayResult } from "./kioskReplayApi";

export const session: KioskBootstrap = {
  station: { id: 2, name: "Desk", kind: "handover" }, makerspace: { id: 1, name: "Space", slug: "space" },
  session_expires_at: "2999-01-01T00:00:00Z", permitted_operations: ["assign_box", "reviewed_issue", "reviewed_return"],
};
export const lease: KioskLease = {
  lease_id: "lease-uuid", lease_token: "SENSITIVE-LEASE", session_id: "session-uuid", actor_id: 3,
  expires_at: "2999-01-01T00:00:00Z", allowed_actions: [], permitted_operations: session.permitted_operations,
};
export const work: KioskWorkPackage = {
  kind: "reviewed_request", id: 7, status: "accepted", display_label: "Request #7", person_display: "PRIVATE-HUMAN",
  box: null, lines: [{ item_id: 5, label: "Drill", quantity: 1, returned: 0 }], return_resolutions: [],
  expires_at: "2999-01-01T00:00:00Z", command_age_limit_seconds: 900, evidence_max_bytes: 4 * 1024 * 1024,
};
export function draft(requestId = 7): ReplayEnvelope {
  return { kind: "assign_box", version: 1, client_command_id: crypto.randomUUID(), aggregate_id: crypto.randomUUID(),
    sequence: 1, client_created_at: new Date().toISOString(), payload: { request_id: requestId, box_code: "PRIVATE-QR" } };
}
export function replayResult(envelope: ReplayEnvelope, state: ReplayResult["state"] = "succeeded"): ReplayResult {
  return { replay_id: "server-id", client_command_id: envelope.client_command_id, state, kind: envelope.kind,
    expires_at: "2999-01-01T00:00:00Z", evidence_id: null, result_request_id: 7,
    result_loan_id: null, result_return_event_id: null, failure_code: null, failure_detail: null };
}
