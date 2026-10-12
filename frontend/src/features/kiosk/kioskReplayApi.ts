// The replay bearer lease identifies the human after a normal browser login expires.
// These calls deliberately use the Station cookie + lease, with no login refresh.
import { configuredApiUrl } from "../../lib/runtimeConfig";
import { StructuredApiError } from "../../lib/api/errors";
import type { ApiErrorBody } from "../../lib/api/errors";
import type { UploadResponse } from "../staff/panels/EvidenceUpload";

type Resolution = {
  item_id: number;
  returned?: number;
  damaged?: number;
  missing?: number;
  assets?: { asset_id: number; outcome: "returned" | "damaged" | "missing" }[];
};

type EnvelopeIdentity = {
  client_command_id: string;
  version: 1;
  aggregate_id: string;
  sequence: number;
  predecessor_client_id?: string | null;
  client_created_at: string;
};

type Photo = {
  content_type: string;
  size_bytes?: number | null;
};

export type ReplayEnvelope = EnvelopeIdentity & (
  | { kind: "assign_box"; payload: { request_id: number; box_code: string }; evidence?: null }
  | { kind: "reviewed_issue"; evidence: Photo & { evidence_type: "issue" }; payload: {
    request_id: number; remark?: string; asset_qr_payloads?: string[];
    rejects?: { item_id: number; broken?: number; disposition?: "needs_fix" | "remove" }[];
  } }
  | { kind: "reviewed_return"; evidence: Photo & { evidence_type: "return" }; payload: {
    request_id: number; remark: string; box_code: string; resolutions: Resolution[];
  } }
  | { kind: "direct_handout"; evidence: Photo & { evidence_type: "issue" }; payload: {
    borrower_id: number; remark?: string; container_id?: number | null;
    qr_payloads?: string[]; items?: { product_id: number; quantity: number }[];
  } }
  | { kind: "direct_return"; evidence: Photo & { evidence_type: "return" }; payload: {
    loan_id?: number; notes: string; qr_payload?: string; resolutions?: Resolution[];
  } }
);

export type ReplayResult = {
  replay_id: string;
  client_command_id: string;
  state: "prepared" | "claimed" | "succeeded" | "failed";
  kind: ReplayEnvelope["kind"];
  expires_at: string;
  evidence_id: number | null;
  result_request_id: number | null;
  result_loan_id: number | null;
  result_return_event_id: number | null;
  failure_code: string | null;
  failure_detail: string | null;
  upload?: UploadResponse | null;
};

async function replayRequest(token: string, lease: string, suffix: string, envelope: ReplayEnvelope, apiBase?: string) {
  const response = await fetch(
    `${apiBase ?? configuredApiUrl().replace(/\/api$/, "/api/v1")}/kiosk-stations/${encodeURIComponent(token)}/replay/${suffix}`,
    {
      method: "POST", credentials: "include", cache: "no-store",
      signal: AbortSignal.timeout(30_000),
      headers: { "Content-Type": "application/json", "X-Station-CSRF": "1", "X-Kiosk-Operator-Lease": lease },
      body: JSON.stringify(envelope),
    },
  );
  if (!response.ok) {
    const body: ApiErrorBody = await response.json().catch(() => ({}));
    throw new StructuredApiError(response.status, body);
  }
  return await response.json() as ReplayResult;
}

export function prepareReplay(token: string, lease: string, envelope: ReplayEnvelope, apiBase?: string) {
  return replayRequest(token, lease, "prepare/", envelope, apiBase);
}

export function executeReplay(token: string, lease: string, envelope: ReplayEnvelope, apiBase?: string) {
  return replayRequest(token, lease, `${encodeURIComponent(envelope.client_command_id)}/execute/`, envelope, apiBase);
}
