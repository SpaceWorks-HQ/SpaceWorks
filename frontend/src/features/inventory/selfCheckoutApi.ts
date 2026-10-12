import { tenantPublicRequest } from "../../lib/api";
import type { KitCount } from "./KitChecklist";

export type PublicToolLoanResult = {
  public_token: string;
  status: string;
  items: { product_name: string; quantity: number }[];
};

export type PublicEvidenceUploadResponse = {
  evidence_id: number;
  upload_url: string;
  fields: Record<string, string>;
  object_key: string;
  method?: string;
  headers?: Record<string, string>;
};

export function requestPublicEvidenceUpload(
  slug: string,
  body: {
    evidence_type: "issue" | "return";
    content_type: string;
    size_bytes?: number;
  },
) {
  return tenantPublicRequest<PublicEvidenceUploadResponse>(
    slug,
    `/public/${slug}/tools/evidence-url`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export async function uploadPublicEvidenceFile(
  presigned: PublicEvidenceUploadResponse,
  file: File,
) {
  if (presigned.method === "PUT") {
    const upload = await fetch(presigned.upload_url, {
      method: "PUT",
      body: file,
      headers: presigned.headers,
    });
    if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
    return;
  }

  const formData = new FormData();
  Object.entries(presigned.fields).forEach(([key, value]) => formData.append(key, value));
  formData.append("file", file);
  const upload = await fetch(presigned.upload_url, { method: "POST", body: formData });
  if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
}

export function checkoutTool(
  slug: string,
  body: {
    payload: string;
    evidence_id: number;
    remark?: string;
    kit_checklist?: KitCount[];
  },
) {
  return tenantPublicRequest<PublicToolLoanResult>(
    slug,
    `/public/${slug}/tools/checkout`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function returnTool(
  slug: string,
  body: {
    payload: string;
    evidence_id: number;
    remark: string;
    kit_checklist?: KitCount[];
  },
) {
  return tenantPublicRequest<PublicToolLoanResult>(
    slug,
    `/public/${slug}/tools/return`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}
