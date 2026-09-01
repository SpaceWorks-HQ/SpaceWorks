import { apiGet, publicV1Request, tenantPublicRequest } from "../../lib/api";
import type {
  Makerspace,
  PaginatedResponse,
  Product,
  PublicCategory,
  PublicToolLoan,
  PublicRequestStatus,
  RequestSubmitResponse,
} from "../../types/inventory";

export const publicMakerspacesKey = ["public-makerspaces"] as const;

export const publicCategoriesKey = (slug: string) =>
  ["public-categories", slug] as const;
export const publicInventoryKey = (
  slug: string,
  page: number,
  query: string,
  category?: string,
  sort?: string,
) =>
  [
    "public-inventory",
    slug,
    page,
    query,
    category ?? "",
    sort ?? "name",
  ] as const;

export async function fetchPublicMakerspaces(): Promise<Makerspace[]> {
  return apiGet<Makerspace[]>("/public/makerspaces/");
}

export async function fetchPublicCategories(
  slug: string,
): Promise<PublicCategory[]> {
  return apiGet<PublicCategory[]>(`/public/${slug}/inventory/categories/`);
}

export async function fetchPublicInventory(
  slug: string,
  page: number,
  query: string,
  category?: string,
  sort?: string,
): Promise<PaginatedResponse<Product>> {
  const params = new URLSearchParams();
  if (page > 1) {
    params.set("page", String(page));
  }
  if (query.trim()) {
    params.set("q", query.trim());
  }
  if (category) {
    params.set("category", category);
  }
  if (sort && sort !== "name") {
    params.set("sort", sort);
  }

  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiGet<PaginatedResponse<Product>>(
    `/public/${slug}/inventory/${suffix}`,
  );
}


export async function submitPublicRequest(
  slug: string,
  payload: {
    requested_for: string;
    items: { product_id: number; quantity: number }[];
    // Account-less submissions only. The backend requires name and email (phone is
    // optional) and rejects the request without them.
    contact_name?: string;
    contact_email?: string;
    contact_phone?: string;
    // Honeypot. The serializer pops it and a filled value gets the decoy response, so it
    // is sent on every submission, authenticated or not -- the backend checks both.
    website?: string;
  },
  // Required by the backend for account-less submissions, and the reason a retry cannot
  // create a second request: the same key with the same payload returns the original,
  // a different payload is refused.
  idempotencyKey?: string,
): Promise<RequestSubmitResponse> {
  return tenantPublicRequest<RequestSubmitResponse>(
    slug,
    `/public/${slug}/requests`,
    {
      method: "POST",
      body: JSON.stringify(payload),
      ...(idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    },
  );
}

export async function fetchRequestStatus(
  publicToken: string,
): Promise<PublicRequestStatus> {
  return publicV1Request<PublicRequestStatus>(
    `/public/requests/${publicToken}/status`,
  );
}

export async function publicToolCheckout(
  slug: string,
  payload: {
    payload: string;
    evidence_id: number;
    remark?: string;
  },
): Promise<PublicToolLoan> {
  return tenantPublicRequest<PublicToolLoan>(
    slug,
    `/public/${slug}/tools/checkout`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function publicToolReturn(
  slug: string,
  payload: {
    payload: string;
    evidence_id: number;
    remark: string;
    report_problem?: boolean;
    problem_note?: string;
  },
): Promise<PublicToolLoan> {
  return tenantPublicRequest<PublicToolLoan>(
    slug,
    `/public/${slug}/tools/return`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}
