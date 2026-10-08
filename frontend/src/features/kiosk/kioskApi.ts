// Typed calls for the phase 9b kiosk Station. The Station cookie is HttpOnly and
// path-bound, so the browser sends it with `credentials: "include"`; the operator lease
// is held only in memory and sent as a header. Nothing here is persisted.
import { API_V1_URL, staffRequest, StructuredApiError } from "../../lib/api";

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
    headers: { ...STATION_HEADERS, "X-Kiosk-Operator-Lease": lease },
    body: JSON.stringify({ version: 1, kind, payload }),
  });
}
