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
  client_type: "server" | "browser";
  last_seen_at: string | null;
  allowed_origins: string[];
  scopes: string[];
  is_active: boolean;
  created_at: string;
};

export type ApiClientScopeOption = {
  value: string;
  label: string;
  description: string;
  group: string;
  grantable: boolean;
  lock_reason: string | null;
};

export type ApiClientScopeCatalog = {
  count: number;
  next: string | null;
  previous: string | null;
  results: ApiClientScopeOption[];
};

const browserClientScopes = new Set([
  "legacy:v1", "public:read", "public:write", "public:*", "admin:read", "reports:read",
]);
const browserScopeLockReason = "Browser clients may only use public/read scopes.";

export function scopeOptionsForClient(
  options: ApiClientScopeOption[],
  clientType: ApiClient["client_type"],
) {
  if (clientType !== "browser") return options;
  return options.map((option) => browserClientScopes.has(option.value) ? option : {
    ...option,
    grantable: false,
    lock_reason: browserScopeLockReason,
  });
}

export type ApiClientCreateResponse = ApiClient & {
  client_secret: string;
};

export type ApiSettings = {
  public_code: string;
  cors_allowed_origins: string[];
};

export const apiKeyRequestsQueryKey = (makerspaceId: number) => ["api-key-requests", makerspaceId];
export const apiClientsQueryKey = (makerspaceId: number) => ["api-clients", makerspaceId];
export const apiClientScopesQueryKey = (makerspaceId: number) => ["api-client-scopes", makerspaceId];
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

export function createApiClient(
  makerspaceId: number,
  label: string,
  allowedOrigins: string[],
  scopes: string[],
) {
  return staffRequest<ApiClientCreateResponse>(`/admin/makerspace/${makerspaceId}/api-clients`, {
    method: "POST",
    body: JSON.stringify({
      label,
      allowed_origins: allowedOrigins,
      scopes,
    }),
  });
}

export function updateApiClientScopes(clientId: number, scopes: string[]) {
  return staffRequest<ApiClient>(`/admin/api-clients/${clientId}`, {
    method: "PATCH",
    body: JSON.stringify({ scopes }),
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
