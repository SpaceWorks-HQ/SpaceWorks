import { API_V1_URL } from "../../lib/api";
import { loadWorkPackage, takeOperatorLease, type KioskBootstrap } from "./kioskApi";
import { normalizeEvidence } from "./offlineEvidence";
import { enqueueCommand, saveWorkPackage } from "./offlineQueueStore";
import type { RecoveryReplay } from "./useKioskReplays";
import type { ReplayEnvelope } from "./kioskReplayApi";

export async function loadCorrectiveWork(token: string, session: KioskBootstrap, row: RecoveryReplay) {
  if (session.makerspace.id !== row.makerspace_id || session.station.kind !== "handover") {
    throw new Error("Use a handover Station in this failure's makerspace.");
  }
  // A new current lease creates a separate encrypted scope; original failed work
  // and evidence remain untouched, including on browsers holding that old shift.
  const lease = await takeOperatorLease(token);
  if (!lease.permitted_operations.includes(row.operation_kind)) throw new Error("This operator cannot perform the correction.");
  const direct = row.operation_kind === "direct_return";
  const id = direct ? row.recovery_loan_id : row.recovery_request_id;
  if (!id || row.operation_kind === "direct_handout") throw new Error("No retained subject can prove replacement compatibility.");
  const work = await loadWorkPackage(token, lease.lease_token, direct ? "direct_loan" : "reviewed_request", id);
  return saveWorkPackage(token, API_V1_URL, session, lease, work);
}

export async function captureCorrection(queue: Awaited<ReturnType<typeof loadCorrectiveWork>>, row: RecoveryReplay,
  inputs: { box: string; remark: string; assetQrs: string; photo: File | null }) {
  const loaded = queue.works[0];
  const work = loaded.work;
  const returning = row.operation_kind.endsWith("return");
  const image = row.operation_kind === "assign_box" ? undefined
    : inputs.photo ? await normalizeEvidence(inputs.photo, work.evidence_max_bytes) : undefined;
  const identity = { version: 1 as const, client_command_id: crypto.randomUUID(), aggregate_id: crypto.randomUUID(),
    sequence: 1, client_created_at: new Date().toISOString() };
  const evidence = image ? { content_type: image.type, size_bytes: image.size,
    evidence_type: returning ? "return" as const : "issue" as const } : undefined;
  const resolutions = work.lines.filter((line) => line.quantity > line.returned).map((line) => ({
    item_id: line.item_id, returned: line.quantity - line.returned,
  }));
  const payload = row.operation_kind === "assign_box" ? { request_id: work.id, box_code: inputs.box.trim() }
    : row.operation_kind === "reviewed_issue" ? { request_id: work.id, remark: inputs.remark.trim(),
      asset_qr_payloads: inputs.assetQrs.split(/\r?\n/).map((value) => value.trim()).filter(Boolean), rejects: [] }
    : row.operation_kind === "reviewed_return" ? { request_id: work.id, box_code: inputs.box.trim(), remark: inputs.remark.trim(), resolutions }
    : { loan_id: work.id, qr_payload: inputs.box.trim(), notes: inputs.remark.trim(), resolutions };
  return enqueueCommand(queue.scope, loaded.id, { ...identity, kind: row.operation_kind,
    payload, ...(evidence ? { evidence } : {}) } as ReplayEnvelope, image, row.id);
}
