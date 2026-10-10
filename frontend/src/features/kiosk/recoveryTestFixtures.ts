import type { RecoveryReplay } from "./useKioskReplays";

export const failedReplay: RecoveryReplay = {
  id: "c3e9a640-2485-4bde-a9e3-c9e250b671e3", makerspace_id: 1, station_id: 2,
  station_name: "Front desk", station_kind: "handover", operator_display: "Operator",
  operation_kind: "reviewed_issue", operation_version: 1, aggregate_id: "aggregate", sequence: 2, state: "failed",
  created_at: "2026-10-10T10:00:00Z", client_created_at: "2026-10-10T10:00:00Z",
  completed_at: "2026-10-10T10:01:00Z", expires_at: "2026-10-10T18:00:00Z", retained_until: "2026-10-17T10:01:00Z",
  failure_code: "qr_revoked", failure_detail: "The scanned QR is no longer active in this makerspace.",
  subject_request_id: 7, subject_loan_id: null, recovery_request_id: 7, recovery_loan_id: null,
  result_request_id: null, result_loan_id: null, result_return_event_id: null,
  predecessor_id: "preceding", predecessor_state: "succeeded", evidence_id: 9, can_view_evidence: true,
  resolution_code: null, resolved_at: null, resolved_by_display: null, replacement_command_id: null,
};
