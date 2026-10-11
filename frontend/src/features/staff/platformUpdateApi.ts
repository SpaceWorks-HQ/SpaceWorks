import { staffRequest } from "../../lib/api";

export type UpdateStatus = "idle" | "queued" | "running" | "failed";
export type UpdateChannel = "stable" | "beta";
export type PlatformUpdateSettings = {
  automatic_updates_enabled: boolean;
  channel: UpdateChannel;
  status: UpdateStatus;
  current_version: string;
  available_version: string;
  target_version: string;
  update_requested_at: string | null;
  last_checked_at: string | null;
  last_updated_at: string | null;
  last_backup_at: string | null;
  last_backup_name: string;
  last_error: string;
  updated_at: string;
  release_notes: string;
  release_url: string;
  running_since: string | null;
  is_stuck: boolean;
  pre_update_version: string;
  pre_update_archive: string | null;
  rollback_restore: string | null;
  rollback_available: boolean;
  rollback_refusal: string;
  rollback_refusal_detail: string;
  rollback_active: boolean;
};

export const UPDATE_QUERY_KEY = ["platform-update-settings"];
export const UPDATE_PATH = "/admin/platform/update-settings";
export const recoverUpdate = () => staffRequest<PlatformUpdateSettings>(`${UPDATE_PATH}/recover`, { method: "POST" });
export const rollbackUpdate = (snapshot: { archive_id: string; confirm_version: string }) =>
  staffRequest<{ id: string }>(`${UPDATE_PATH}/rollback`, {
    method: "POST", body: JSON.stringify({ ...snapshot, confirm_data_loss: true }),
  });
