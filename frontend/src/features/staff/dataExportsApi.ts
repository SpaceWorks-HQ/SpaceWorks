import { staffRequest } from "../../lib/api";

export type DataExportJob = {
  id: string;
  fidelity: "REDACTED";
  status: "pending" | "running" | "available" | "failed";
  manifest: {
    total_rows?: number;
    row_counts?: Record<string, number>;
    deadline?: { outcome?: string };
  };
  failure_code: string;
  failure_detail: string;
  snapshot_at: string | null;
  completed_at: string | null;
  expires_at: string;
  created_at: string;
};

export function listDataExports(makerspaceId: number) {
  return staffRequest<DataExportJob[]>(
    `/admin/makerspace/${makerspaceId}/data-exports`,
  );
}

export function requestDataExport(makerspaceId: number) {
  return staffRequest<DataExportJob>(
    `/admin/makerspace/${makerspaceId}/data-exports`,
    { method: "POST", body: JSON.stringify({ fidelity: "REDACTED" }) },
  );
}

export function issueDataExportDownload(makerspaceId: number, jobId: string) {
  return staffRequest<{ url: string; expires_at: string }>(
    `/admin/makerspace/${makerspaceId}/data-exports/${jobId}/download-url`,
    { method: "POST" },
  );
}
