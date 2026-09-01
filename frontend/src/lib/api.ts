import { removeStorage } from "./safeStorage";
import { configuredApiUrl } from "./runtimeConfig";

export const API_URL = configuredApiUrl();

export const API_V1_URL = API_URL.replace(/\/api$/, "/api/v1");
const PUBLIC_CLIENT_ID = (import.meta.env.VITE_PUBLIC_CLIENT_ID ?? "").trim();
const ACCESS_TOKEN_KEY = "makerspace.access";
const REFRESH_CSRF_HEADER = "X-Refresh-CSRF";
let runtimePublishableKey = (import.meta.env.VITE_PUBLIC_API_KEY ?? "").trim();
let accessToken = "";
let accessRefreshPromise: Promise<boolean> | null = null;
const tenantPublishableKeys = new Map<string, string>();
// The tenant most recently bootstrapped in this session. Member and status requests
// carry no slug of their own, so without this they would send no client credential at
// all on the central /m/:slug routes -- fine today, a 401 the moment enforcement is on.
let activeTenantSlug = "";
const authExpiredListeners = new Set<() => void>();

export type TenantBootstrap = {
  makerspace: {
    id: number;
    name: string;
    slug: string;
    public_code: string;
    location: string;
    map_url?: string;
    logo_url?: string | null;
    cover_image_url?: string | null;
    geofence_enabled: boolean;
    public_stats_enabled?: boolean;
    membership_policy: "request" | "open" | "invite_only";
    // Present only when the makerspace opted into account-less borrow requests. Absent
    // means an account is required -- the backend omits the key otherwise to keep the
    // bootstrap payload byte-for-byte unchanged for everyone else.
    request_access?: "anyone";
  };
  frontend: {
    type: string;
    hostname: string;
    allowed_origins: string[];
  };
  modules: string[];
  features: string[];
  workflows: string[];
  theme: Record<string, string>;
  branding: Record<string, string>;
  email_enabled: boolean;
  public_api: {
    base_url: string;
    publishable_key: string;
    inventory_path: string;
  };
};

export type StaffAuthUser = {
  username: string;
  email_verified: boolean;
  role: string;
  is_superuser: boolean;
  must_change_password: boolean;
  makerspaces: {
    id: number;
    slug: string;
    role: string | null;
    role_id: number | null;
    role_name: string;
    role_slug: string | null;
    source: "membership" | "organization";
    actions: string[];
    can_configure_machine_types: boolean;
    is_machine_only: boolean;
    can_refer: boolean;
    can_verify: boolean;
    verified_at: string | null;
    referrals_enabled: boolean;
  }[];
};

export type PasswordLoginRequestedSurface = "member" | "staff";
export type PasswordLoginSurface = PasswordLoginRequestedSurface | "verification_only";
export type PasswordLoginRequest = {
  username: string;
  password: string;
  surface: PasswordLoginRequestedSurface;
};
export type PasswordLoginResponse<TUser = unknown> = {
  access: string;
  surface: PasswordLoginSurface;
  user: TUser;
};

export type ApiErrorBody = Record<string, unknown> & {
  detail?: unknown;
  code?: unknown;
};

export class StructuredApiError extends Error {
  readonly status: number;
  readonly detail?: string;
  readonly code?: string;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    const flattenMessages = (value: unknown): string[] => {
      if (typeof value === "string") return value.trim() ? [value.trim()] : [];
      if (Array.isArray(value)) return value.flatMap(flattenMessages);
      if (value && typeof value === "object") return Object.values(value).flatMap(flattenMessages);
      return [];
    };
    const detail = typeof body.detail === "string" ? body.detail.trim() : "";
    super(detail || Object.values(body).flatMap(flattenMessages).join(" ") || `Request failed (${status})`);
    this.name = "StructuredApiError";
    this.status = status;
    this.detail = detail || undefined;
    this.code = typeof body.code === "string" ? body.code : undefined;
    this.body = body;
  }
}

function apiError(status: number, value: unknown) {
  const body = value && typeof value === "object" && !Array.isArray(value)
    ? value as ApiErrorBody
    : {};
  return new StructuredApiError(status, body);
}

function messageForStatus(status: number): string {
  if (status === 401) {
    return "Inventory client is not authorized";
  }

  if (status === 404) {
    return "Makerspace not found";
  }

  if (status >= 500) {
    return "Inventory service is unavailable";
  }

  return "Unable to load inventory";
}

async function publicHeaders(publishableKey?: string): Promise<HeadersInit> {
  if (PUBLIC_CLIENT_ID) {
    return { "X-Client-Id": PUBLIC_CLIENT_ID };
  }
  const key =
    publishableKey?.trim() ||
    runtimePublishableKey ||
    tenantPublishableKeys.get(activeTenantSlug) ||
    "";
  return key ? { "X-Publishable-Key": key } : {};
}

export function setRuntimePublishableKey(key: string) {
  runtimePublishableKey = key.trim();
}

export function cacheTenantPublishableKey(slug: string, key: string) {
  const normalized = slug.trim();
  const normalizedKey = key.trim();
  if (normalized && normalizedKey) {
    tenantPublishableKeys.set(normalized, normalizedKey);
    activeTenantSlug = normalized;
  }
}

export function getAccessToken() {
  return accessToken;
}

export function cleanupLegacyAccessToken() {
  removeStorage(ACCESS_TOKEN_KEY);
}

export function authHeaders(): HeadersInit {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export function addAuthExpiredListener(listener: () => void) {
  authExpiredListeners.add(listener);
  return () => {
    authExpiredListeners.delete(listener);
  };
}

export function expireStaffAuthSession() {
  clearAccessToken();
  authExpiredListeners.forEach((listener) => listener());
}

function canRefreshAfterUnauthorized(path: string) {
  return !["/auth/login", "/auth/refresh", "/auth/logout"].includes(path);
}

export async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: await publicHeaders(),
  });

  if (!response.ok) {
    throw new Error(`${messageForStatus(response.status)} (${response.status})`);
  }

  return (await response.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  return fetchJson<T>(`${API_URL}${path}`);
}

export async function publicV1Request<T>(
  path: string,
  options: RequestInit = {},
  publishableKey?: string,
): Promise<T> {
  const response = await fetch(`${API_V1_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(await publicHeaders(publishableKey)),
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }

  return (await response.json()) as T;
}

export async function bootstrapTenant(params: { tenant?: string; slug?: string }) {
  const search = new URLSearchParams();
  if (params.tenant) search.set("tenant", params.tenant);
  if (params.slug) search.set("slug", params.slug);
  const bootstrap = await publicV1Request<TenantBootstrap>(
    `/bootstrap?${search.toString()}`,
  );
  cacheTenantPublishableKey(
    bootstrap.makerspace.slug,
    bootstrap.public_api.publishable_key,
  );
  return bootstrap;
}

export async function tenantPublicRequest<T>(
  slug: string,
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const normalized = slug.trim();
  let publishableKey = tenantPublishableKeys.get(normalized);
  if (!publishableKey) {
    const bootstrap = await bootstrapTenant({ slug: normalized });
    publishableKey = bootstrap.public_api.publishable_key;
  }
  return publicV1Request<T>(path, options, publishableKey);
}

export function setAccessToken(token: string) {
  accessToken = token;
  cleanupLegacyAccessToken();
}

export function clearAccessToken() {
  accessToken = "";
  cleanupLegacyAccessToken();
}

export async function refreshAccessToken(): Promise<boolean> {
  if (!accessRefreshPromise) {
    accessRefreshPromise = (async () => {
      const response = await fetch(`${API_V1_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: {
          [REFRESH_CSRF_HEADER]: "1",
        },
      }).catch(() => null);

      if (!response?.ok) {
        return false;
      }

      const body = (await response.json().catch(() => ({}))) as { access?: string };
      if (!body.access) {
        return false;
      }

      setAccessToken(body.access);
      return true;
    })().finally(() => {
      accessRefreshPromise = null;
    });
  }

  return accessRefreshPromise;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_V1_URL}/auth/logout`, {
      method: "POST",
      credentials: "include",
      headers: {
        [REFRESH_CSRF_HEADER]: "1",
      },
    });
  } finally {
    clearAccessToken();
  }
}

export async function fetchMe(): Promise<StaffAuthUser> {
  return staffRequest<StaffAuthUser>("/auth/me");
}

/** The authenticated request, up to but not including reading the body.
 *
 * Extracted so a non-JSON response (an SVG, say) can reuse the refresh-and-retry
 * behaviour rather than carrying a second copy of it. A duplicated refresh path is how one
 * caller silently stops recovering from an expired token.
 */
async function staffFetch(
  path: string,
  options: RequestInit = {},
  includePublicCredentials = false,
): Promise<Response> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const makeRequest = async () =>
    fetch(`${API_V1_URL}${path}`, {
      ...options,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(includePublicCredentials ? await publicHeaders() : {}),
        ...authHeaders(),
        ...(options.headers ?? {}),
      },
    });

  let response = await makeRequest();

  if (response.status === 401 && canRefreshAfterUnauthorized(path)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await makeRequest();
      if (response.status === 401) {
        expireStaffAuthSession();
      }
    } else {
      expireStaffAuthSession();
    }
  }
  return response;
}

/** Fetch a binary/non-JSON authenticated resource as a Blob.
 *
 * `<img src>` cannot carry an Authorization header, so an authenticated image has to be
 * fetched and handed to the DOM as an object URL. Callers must revoke that URL.
 */
export async function staffRequestBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const response = await staffFetch(path, options);
  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  return await response.blob();
}

export async function staffRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await staffFetch(path, options);

  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  // 204 No Content (e.g. DRF destroy) has an empty body - parsing it as JSON
  // would throw and surface a successful mutation as a failure.
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function memberRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await staffFetch(path, options, true);
  if (!response.ok) {
    throw apiError(response.status, await response.json().catch(() => ({})));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function downloadStaffFile(path: string, filename: string) {
  const response = await fetch(`${API_V1_URL}${path}`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    throw new Error(`Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
