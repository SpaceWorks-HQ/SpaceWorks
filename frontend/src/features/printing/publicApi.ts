import type { PublicPrinterPool, PublicPrinterQueue, PublicPrinterStatus, PublicPrinterSubmit, PublicPrinterUpload } from "../../generated/api";
import { publicV1Request, tenantPublicRequest } from "../../lib/api";

export type PrintQueue = PublicPrinterQueue & { machine_type_id?: number };
export type PublicFilamentPool = PublicPrinterPool;
export type PrintStatus = PublicPrinterStatus;
export type PrintUploadBody = PublicPrinterUpload;
export type PrintUpload = { url: string; fields: Record<string, string>; method?: string; headers?: Record<string, string> };
export type PrintRequestPayload = PublicPrinterSubmit;

export function fetchPrintQueues(slug: string) {
  return tenantPublicRequest<PrintQueue[]>(slug, `/public/${slug}/machine-service/3d-printer/queues`);
}

export function fetchPublicConsumablePools(slug: string) {
  return tenantPublicRequest<PublicFilamentPool[]>(slug, `/public/${slug}/machine-service/3d-printer/consumable-pools`);
}

export function presignPrintUpload(slug: string, body: PrintUploadBody) {
  return tenantPublicRequest<{ file_id: number; upload: PrintUpload }>(slug, `/public/${slug}/machine-service/3d-printer/uploads`, { method: "POST", body: JSON.stringify(body) });
}

export async function uploadToStorage(upload: PrintUpload, file: File) {
  if (upload.method === "PUT") {
    const res = await fetch(upload.url, { method: "PUT", body: file, headers: upload.headers });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    return;
  }
  const formData = new FormData();
  for (const [key, value] of Object.entries(upload.fields)) formData.append(key, value);
  formData.append("file", file);
  const res = await fetch(upload.url, { method: "POST", body: formData });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
}

export function submitPrintRequest(slug: string, payload: PrintRequestPayload) {
  return tenantPublicRequest<{ public_token: string; status: string }>(slug, `/public/${slug}/machine-service/3d-printer/requests`, { method: "POST", body: JSON.stringify(payload) });
}

export function fetchPrintStatus(publicToken: string) {
  return publicV1Request<PrintStatus>(`/public/machine-service/3d-printer/requests/${publicToken}/status`);
}
