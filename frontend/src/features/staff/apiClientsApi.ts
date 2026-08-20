import { staffRequest } from "../../lib/api";

export type ApiKeyRequest = {
  id: number;
  label: string;
  status: "pending" | "approved" | "rejected";
  resolution_note: string;
  created_at: string;
};

export type ApiClient = {
  id: number;
  label: string;
  client_id: string;
  last_seen_at: string | null;
  allowed_origins: string[];
  is_active: boolean;
  created_at: string;
};

export type ApiClientCreateResponse = ApiClient & {
  client_secret: string;
};

export type ApiSettings = {
  public_code: string;
  cors_allowed_origins: string[];
};

export const apiKeyRequestsQueryKey = (makerspaceId: number) => ["api-key-requests", makerspaceId];
export const apiClientsQueryKey = (makerspaceId: number) => ["api-clients", makerspaceId];
export const apiSettingsQueryKey = (makerspaceId: number) => ["api-settings", makerspaceId];

export function requestApiKey(
  makerspaceId: number,
  label: string,
  reason: string,
  allowedOrigins: string[],
) {
  return staffRequest<ApiKeyRequest>("/admin/api-key-requests", {
    method: "POST",
    body: JSON.stringify({
      makerspace: makerspaceId,
      label,
      reason,
      allowed_origins: allowedOrigins,
    }),
  });
}

export function createApiClient(makerspaceId: number, label: string, allowedOrigins: string[]) {
  return staffRequest<ApiClientCreateResponse>(`/admin/makerspace/${makerspaceId}/api-clients`, {
    method: "POST",
    body: JSON.stringify({
      label,
      allowed_origins: allowedOrigins,
    }),
  });
}

export function deleteApiClient(clientId: number) {
  return staffRequest<void>(`/admin/api-clients/${clientId}`, {
    method: "DELETE",
  });
}

export function rotateApiClient(clientId: number) {
  return staffRequest<ApiClientCreateResponse>(`/admin/api-clients/${clientId}/rotate-secret`, {
    method: "POST",
  });
}

export function splitOrigins(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((origin) => origin.trim())
    .filter(Boolean);
}
