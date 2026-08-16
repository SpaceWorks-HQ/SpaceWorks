import { staffRequest } from "../../lib/api";

export type BackupArchive = {
  id: string;
  scope: "deployment" | "makerspace";
  makerspace: number | null;
  status: "pending" | "running" | "available" | "failed" | "expired";
  manifest: { snapshot_at?: string; postgres?: { source_server_major?: number } };
  size_bytes: number;
  age_encrypted: boolean;
  failure_detail: string;
  expires_at: string;
  created_at: string;
  purge_warning: string;
};

export type RestoreOperation = {
  id: string;
  archive: string;
  kind: "rollback_in_place" | "disaster";
  stage: string;
  decision: "pending" | "proceed" | "reset" | "abort";
  restore_diff: {
    snapshot_at?: string;
    tables_compared?: number;
    tables_changed?: number;
    tables?: Array<{ table: string; security_relevant: boolean; noisy: boolean; live: { row_count: number }; archive: { row_count: number }; row_diff?: unknown }>;
  };
  decision_deadline_at: string | null;
  error_detail: string;
  requested_at: string;
};

export type BackupSettings = {
  automatic_backups_enabled: boolean;
  retention_days: number;
  last_scheduled_at: string | null;
  last_success_at: string | null;
  last_error: string;
};

export const listTenantBackups = (makerspaceId: number) =>
  staffRequest<BackupArchive[]>(`/admin/makerspace/${makerspaceId}/backups`);
export const requestTenantBackup = (makerspaceId: number) =>
  staffRequest<BackupArchive>(`/admin/makerspace/${makerspaceId}/backups`, { method: "POST", body: "{}" });
export const listDeploymentBackups = () => staffRequest<BackupArchive[]>("/admin/platform/backups");
export const requestDeploymentBackup = () =>
  staffRequest<BackupArchive>("/admin/platform/backups", { method: "POST", body: "{}" });
export const issueBackupDownload = (archiveId: string) =>
  staffRequest<{ url: string; expires_at: string; purge_warning: string }>(`/admin/backups/${archiveId}/download-url`, { method: "POST" });
export const getBackupSettings = () => staffRequest<BackupSettings>("/admin/platform/backup-settings");
export const updateBackupSettings = (payload: Partial<BackupSettings>) =>
  staffRequest<BackupSettings>("/admin/platform/backup-settings", { method: "PATCH", body: JSON.stringify(payload) });
export const listRestores = () => staffRequest<RestoreOperation[]>("/admin/platform/restores");
export const requestRestore = (archive: string, kind: RestoreOperation["kind"]) =>
  staffRequest<RestoreOperation>("/admin/platform/restores", { method: "POST", body: JSON.stringify({ archive, kind }) });
export const getRestore = (restoreId: string) => staffRequest<RestoreOperation>(`/admin/platform/restores/${restoreId}`);
export const decideRestore = (restoreId: string, decision: "proceed" | "reset" | "abort") =>
  staffRequest<RestoreOperation>(`/admin/platform/restores/${restoreId}/decision`, { method: "POST", body: JSON.stringify({ decision }) });
