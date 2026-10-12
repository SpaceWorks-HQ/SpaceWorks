import {
  API_V1_URL,
  authHeaders,
  cacheTenantPublishableKey,
  getTenantPublishableKey,
  publicHeaders,
} from "./client";
import { apiError } from "./errors";
import { publicV1Request } from "./requests";
import type { TenantBootstrap } from "./types";

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
  let publishableKey = getTenantPublishableKey(normalized);
  if (!publishableKey) {
    const bootstrap = await bootstrapTenant({ slug: normalized });
    publishableKey = bootstrap.public_api.publishable_key;
  }
  return publicV1Request<T>(path, options, publishableKey);
}

export async function tenantPublicRequestBlob(slug: string, path: string): Promise<Blob> {
  const normalized = slug.trim();
  let publishableKey = getTenantPublishableKey(normalized);
  if (!publishableKey) {
    const bootstrap = await bootstrapTenant({ slug: normalized });
    publishableKey = bootstrap.public_api.publishable_key;
  }
  const response = await fetch(`${API_V1_URL}${path}`, {
    headers: { ...(await publicHeaders(publishableKey)), ...authHeaders() },
  });
  if (!response.ok) throw apiError(response.status, await response.json().catch(() => ({})));
  return response.blob();
}
