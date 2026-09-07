import { API_URL, API_V1_URL, authHeaders, publicHeaders, staffFetch } from "./client";
import { apiError, messageForStatus } from "./errors";
import type { StaffAuthUser } from "./types";

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

export async function fetchMe(): Promise<StaffAuthUser> {
  return staffRequest<StaffAuthUser>("/auth/me");
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

export async function memberRequestBlob(path: string): Promise<Blob> {
  const response = await staffFetch(path, {}, true);
  if (!response.ok) throw apiError(response.status, await response.json().catch(() => ({})));
  return response.blob();
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
