import { API_V1_URL, staffRequest, StructuredApiError } from "../../lib/api";

export type OfflineRosterRegistration = {
  registration_id: number;
  checkin_token: string;
  name: string;
  host_waiver_state: "not_required" | "on_file" | "missing";
};

export type OfflineRoster = {
  lease_token: string;
  lease_id: string;
  server_time: string;
  issued_at: string;
  expires_at: string;
  scan_opens_at: string;
  scan_closes_at: string;
  sync_deadline: string;
  event: { id: number; title: string; starts_at: string; ends_at: string };
  registrations: OfflineRosterRegistration[];
};

export type QueuedCheckIn = {
  operation_id: string;
  checkin_token: string;
  reported_occurred_at: string;
};

export type SyncOutcome = {
  operation_id: string;
  outcome: "applied" | "duplicate_operation" | "already_attended" |
    "registration_changed" | "event_unavailable" | "invalid_token" | "outside_window";
  registration_id?: number;
  attended_at?: string;
};

export type SyncResponse = { recorded_at: string; results: SyncOutcome[] };

export function downloadStaffRoster(eventId: number) {
  return staffRequest<OfflineRoster>(
    `/admin/events/${eventId}/check-in/offline-roster/`,
  );
}

export function syncStaffRoster(eventId: number, roster: OfflineRoster, operations: QueuedCheckIn[]) {
  return staffRequest<SyncResponse>(
    `/admin/events/${eventId}/check-in/offline-sync/`,
    { method: "POST", body: JSON.stringify({ lease_token: roster.lease_token, operations }) },
  );
}

const stationHeaders = { "Content-Type": "application/json", "X-Station-CSRF": "1" };

async function stationRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_V1_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { ...stationHeaders, ...init.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    let body: Record<string, unknown> = {};
    try { body = await response.json() as Record<string, unknown>; } catch { /* no body */ }
    throw new StructuredApiError(response.status, body);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export function startStationSession(token: string, pin: string) {
  return stationRequest<void>(`/event-checkin-stations/${token}/session/`, {
    method: "POST", body: JSON.stringify({ pin }),
  });
}

export function endStationSession(token: string) {
  return stationRequest<void>(`/event-checkin-stations/${token}/session/`, {
    method: "DELETE",
  });
}

export function downloadStationRoster(token: string) {
  return stationRequest<OfflineRoster>(`/event-checkin-stations/${token}/roster/`);
}

export function syncStationRoster(token: string, roster: OfflineRoster, operations: QueuedCheckIn[]) {
  return stationRequest<SyncResponse>(`/event-checkin-stations/${token}/sync/`, {
    method: "POST", body: JSON.stringify({ lease_token: roster.lease_token, operations }),
  });
}
