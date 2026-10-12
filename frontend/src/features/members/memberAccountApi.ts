import { memberRequest } from "../../lib/api";

export type AccountProfile = { display_name: string; first_name: string; last_name: string; phone: string };
export type AccountSession = { id: string; kind: "web" | "device"; created_at: string; expires_at: string | null; last_used_at: string | null; current: boolean };
export type AccountMembership = { status: "active" | "revoked"; renewal_cancelled_at: string | null };
export type SubjectExport = { id: string; status: "pending" | "running" | "available" | "failed"; expires_at: string; created_at: string; failure_detail: string };
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export const accountKey = (id: number) => ["member", "account", id] as const;
const base = (id: number) => `/member/makerspaces/${id}/account`;
export const ownProfile = (id: number) => memberRequest<AccountProfile>(`${base(id)}/profile`);
export const editProfile = (id: number, profile: AccountProfile) => memberRequest<AccountProfile>(`${base(id)}/profile`, { method: "PATCH", body: JSON.stringify(profile) });
export const ownSessions = (id: number, page = 1) => memberRequest<Page<AccountSession>>(`${base(id)}/sessions?page=${page}`);
export const revokeSession = (id: number, session: string) => memberRequest<void>(`${base(id)}/sessions/${encodeURIComponent(session)}`, { method: "DELETE" });
export const ownMembership = (id: number) => memberRequest<AccountMembership>(`${base(id)}/membership`);
export const endMembership = (id: number, action: "cancel" | "leave", reason: string) => memberRequest<AccountMembership>(`${base(id)}/${action}`, { method: "POST", body: JSON.stringify({ reason }) });
export const ownExports = (id: number, page = 1) => memberRequest<Page<SubjectExport>>(`${base(id)}/exports?page=${page}`);
export const requestExport = (id: number) => memberRequest<SubjectExport>(`${base(id)}/exports`, { method: "POST" });
export const exportDownload = (id: number, job: string) => memberRequest<{ url: string; expires_at: string }>(`${base(id)}/exports/${job}/download`, { method: "POST" });
