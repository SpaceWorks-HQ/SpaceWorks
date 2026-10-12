import { staffRequest } from "../../lib/api";

export type CertificationType = {
  id: number; machine_type: number; name: string; description: string;
  validity_days: number | null; is_required_for_service: boolean;
  is_required_for_booking: boolean; is_active: boolean;
};
export type CertificationInput = Omit<CertificationType, "id" | "is_active">;
export type CertificationGrant = {
  id: number; membership: number; member_name: string; granted_at: string;
  expires_at: string | null; revoked_at: string | null; notes: string; is_live: boolean;
};
export type CertificationPage<T> = {
  count: number; next: string | null; previous: string | null;
  results: T[];
};
export type MemberPage = CertificationPage<{ id: number; name: string }>;
export const certificationKeys = {
  types: (space: number) => ["certifications", "types", space] as const,
  grants: (type: number, page?: number) => page === undefined
    ? ["certifications", "grants", type] as const
    : ["certifications", "grants", type, page] as const,
  members: (type: number, page: number) => ["certifications", "members", type, page] as const,
};
export async function getCertificationTypes(space: number): Promise<CertificationType[]> {
  const rows: CertificationType[] = [];
  let page = 1;
  while (true) {
    const result = await staffRequest<CertificationPage<CertificationType>>(`/admin/makerspace/${space}/certification-types?page=${page}`);
    rows.push(...result.results);
    if (!result.next) return rows;
    page += 1;
  }
}
export const createCertificationType = (space: number, input: CertificationInput) =>
  staffRequest<CertificationType>(`/admin/makerspace/${space}/certification-types`, { method: "POST", body: JSON.stringify(input) });
export const updateCertificationType = (id: number, input: CertificationInput) =>
  staffRequest<CertificationType>(`/admin/certification-types/${id}`, { method: "PATCH", body: JSON.stringify(input) });
export const deactivateCertificationType = (id: number) =>
  staffRequest<CertificationType>(`/admin/certification-types/${id}`, { method: "DELETE" });
export const getCertificationGrants = (id: number, page = 1) =>
  staffRequest<CertificationPage<CertificationGrant>>(`/admin/certification-types/${id}/grants?page=${page}`);
export const getCertificationMembers = (id: number, page: number) =>
  staffRequest<MemberPage>(`/admin/certification-types/${id}/members?page=${page}`);
export const grantCertification = (id: number, membership_id: number, notes: string) =>
  staffRequest<CertificationGrant>(`/admin/certification-types/${id}/grants`, { method: "POST", body: JSON.stringify({ membership_id, notes }) });
export const renewCertification = (id: number, notes: string) =>
  staffRequest<CertificationGrant>(`/admin/certification-grants/${id}/renew`, { method: "POST", body: JSON.stringify({ notes }) });
export const revokeCertification = (id: number, notes: string) =>
  staffRequest<CertificationGrant>(`/admin/certification-grants/${id}/revoke`, { method: "POST", body: JSON.stringify({ notes }) });
