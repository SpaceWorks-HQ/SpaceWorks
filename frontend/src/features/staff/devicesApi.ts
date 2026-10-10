import { staffRequest } from "../../lib/api";

export type DeviceKind = "printer" | "label_printer" | "generic";
export type Device = {
  id: string; makerspace: number; name: string; kind: DeviceKind;
  status: "pending" | "active" | "revoked";
  key_fingerprint: string | null; key_version: number;
  last_seen_at: string | null; offline_since: string | null;
  offline_notified_at: string | null; offline_threshold_seconds: number;
};
export type DevicePage = { count: number; next: string | null; previous: string | null; results: Device[] };
export type EnrollmentGrant = {
  enrollment_id: string; device_id: string; purpose: "enroll" | "rotate" | "reactivate";
  token: string; expires_at: string;
};
export type DeviceCreate = { name: string; kind: DeviceKind; offline_threshold_seconds: number };

export const devicesApi = {
  list: (space: number, page: number) => staffRequest<DevicePage>(`/admin/makerspace/${space}/devices?page=${page}`),
  detail: (id: string) => staffRequest<Device>(`/admin/devices/${id}`),
  create: (space: number, data: DeviceCreate) => staffRequest<{ device: Device; enrollment: EnrollmentGrant }>(
    `/admin/makerspace/${space}/devices`, { method: "POST", body: JSON.stringify(data) },
  ),
  update: (id: string, data: { name: string; offline_threshold_seconds: number }) => staffRequest<Device>(
    `/admin/devices/${id}`, { method: "PATCH", body: JSON.stringify(data) },
  ),
  enrollment: (id: string) => staffRequest<EnrollmentGrant>(`/admin/devices/${id}/enrollments`, { method: "POST" }),
  revoke: (id: string) => staffRequest<Device>(`/admin/devices/${id}/revoke`, { method: "POST" }),
};
