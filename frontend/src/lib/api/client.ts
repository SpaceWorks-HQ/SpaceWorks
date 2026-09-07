import { removeStorage } from "../safeStorage";
import { configuredApiUrl } from "../runtimeConfig";

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

export async function publicHeaders(publishableKey?: string): Promise<HeadersInit> {
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

/** Read a cached tenant key. Internal to the api modules -- not re-exported by the barrel. */
export function getTenantPublishableKey(slug: string) {
  return tenantPublishableKeys.get(slug);
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

/** The authenticated request, up to but not including reading the body.
 *
 * Extracted so a non-JSON response (an SVG, say) can reuse the refresh-and-retry
 * behaviour rather than carrying a second copy of it. A duplicated refresh path is how one
 * caller silently stops recovering from an expired token.
 */
export async function staffFetch(
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
