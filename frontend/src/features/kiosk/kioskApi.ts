// Typed calls for the phase 9b kiosk Station. The Station cookie is HttpOnly and
// path-bound, so the browser sends it with `credentials: "include"`; the operator lease
// is held only in memory and sent as a header. Nothing here is persisted.
import { API_V1_URL, staffRequest, StructuredApiError } from "../../lib/api";
import type { UploadResponse } from "../staff/panels/EvidenceUpload";

export type KioskBootstrap = {
  station: { id: number; name: string; kind: "scanner" | "handover" };
  makerspace: { id: number; slug: string; name: string };
  session_expires_at: string;
  permitted_operations: string[];
};

export type KioskLease = {
  lease_token: string;
  lease_id: string;
  expires_at: string;
  allowed_actions: string[];
  permitted_operations: string[];
};

export type KioskWorkPackage = {
  kind: "reviewed_request" | "direct_loan";
  id: number;
  status: string;
  display_label: string;
  person_display: string;
  box: string | null;
  lines: { item_id: number; label: string; quantity: number; returned: number }[];
  return_resolutions: string[];
  expires_at: string;
  command_age_limit_seconds: number;
  evidence_max_bytes: number;
};

const STATION_HEADERS = { "Content-Type": "application/json", "X-Station-CSRF": "1" };

function stationPath(token: string, suffix: string) {
  return `/kiosk-stations/${encodeURIComponent(token)}/${suffix}`;
}

export async function startKioskSession(token: string, pin: string, makerspaceSlug?: string) {
  const response = await fetch(`${API_V1_URL}${stationPath(token, "session/")}`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: STATION_HEADERS,
    body: JSON.stringify(makerspaceSlug ? { pin, makerspace_slug: makerspaceSlug } : { pin }),
  });
  if (!response.ok) throw new StructuredApiError(response.status, {});
  return (await response.json()) as KioskBootstrap;
}

export async function endKioskSession(token: string) {
  await fetch(`${API_V1_URL}${stationPath(token, "session/")}`, {
    method: "DELETE", credentials: "include", cache: "no-store", headers: STATION_HEADERS,
  });
}

export function takeOperatorLease(token: string) {
  return staffRequest<KioskLease>(stationPath(token, "operator-lease/"), {
    method: "POST", headers: STATION_HEADERS,
  });
}

export function runOnlineCommand<T>(token: string, lease: string, kind: string, payload: object) {
  return staffRequest<{ kind: string; result: T }>(stationPath(token, "commands/online/"), {
    method: "POST",
    headers: leaseHeaders(lease),
    body: JSON.stringify({ version: 1, kind, payload }),
  });
}

function leaseHeaders(lease: string) {
  return { ...STATION_HEADERS, "X-Kiosk-Operator-Lease": lease };
}

export function loadWorkPackage(token: string, lease: string, kind: KioskWorkPackage["kind"], id: number) {
  return staffRequest<KioskWorkPackage>(stationPath(token, "work-package/"), {
    method: "POST", headers: leaseHeaders(lease), body: JSON.stringify({ kind, id }),
  });
}

export function prepareEvidence(token: string, lease: string, body: object) {
  return staffRequest<UploadResponse>(stationPath(token, "evidence/prepare/"), {
    method: "POST", headers: leaseHeaders(lease), body: JSON.stringify(body),
  });
}
