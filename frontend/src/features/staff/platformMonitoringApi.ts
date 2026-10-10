import { staffRequest } from "../../lib/api";

export type CheckStatus = "ok" | "warn" | "error";
export type ResourceUsage = { key: string; label: string; used: number | null; limit: number | null; unit: "bytes" | "count" };
export type TenantUsage = { makerspace_id: number; managed: boolean; resources: ResourceUsage[] };
export type Problem = { key: string; status: CheckStatus; message: string; fix_url: string; makerspace_id: number | null };
export type Problems = { checked_at: string; status: CheckStatus; results: Problem[] };
export type PlatformDashboard = {
  checked_at: string;
  tenants_by_state: Record<string, number>;
  usage_totals: Record<string, number>;
  tenants: { id: number; name: string; slug: string; usage: TenantUsage }[];
  backup: { status: string; automatic_enabled: boolean; last_success_at: string | null };
  offsite: { name: string; state: string; verified_at: string | null; has_error: boolean }[];
  scheduler: { name: string; cadence_minutes: number; last_run_at: string | null; status: CheckStatus }[];
  failed_deliveries: { email: number; notifications: number };
  updates: { status: string; current_version: string; available_version: string; pending: boolean } | null;
};

// These routes are hand-written until the coordinator regenerates the schema.
export const getPlatformDashboard = () => staffRequest<PlatformDashboard>("/admin/platform/dashboard");
export const getPlatformProblems = () => staffRequest<Problems>("/admin/platform/problems");
export const getTenantUsage = (id: number) => staffRequest<TenantUsage>(`/admin/makerspace/${id}/usage`);

export function usageAmount(value: number | null, unit: ResourceUsage["unit"]) {
  if (value === null) return "Unavailable";
  return unit === "bytes" ? `${(value / 1024 ** 2).toLocaleString(undefined, { maximumFractionDigits: 1 })} MiB` : value.toLocaleString();
}

export function monitoringDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "No execution recorded";
}
