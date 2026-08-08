import { staffRequest } from "../../../lib/api";

export type StaffRole = {
  id: number;
  makerspace_id: number;
  name: string;
  slug: string;
  granted_actions: string[];
  legacy_role: string | null;
  is_default: boolean;
  is_protected: boolean;
  member_count: number;
  created_at: string;
  updated_at: string;
};

export type Capability = {
  value: string;
  label: string;
  description: string;
  group: string;
  grantable: boolean;
  lock_reason: string | null;
};

export type StaffMembershipRow = {
  id: number;
  user: { id: number; username: string; email: string; access_status: string };
  makerspace_id: number;
  makerspace_slug: string;
  role: string;
  assigned_role: Pick<StaffRole, "id" | "name" | "slug" | "legacy_role" | "is_default" | "is_protected"> | null;
  created_at: string;
};

export function listRoles(msId: number) {
  return staffRequest<StaffRole[]>(`/admin/makerspaces/${msId}/roles`);
}

export function createRole(msId: number, body: Pick<StaffRole, "name" | "granted_actions">) {
  return staffRequest<StaffRole>(`/admin/makerspaces/${msId}/roles`, { method: "POST", body: JSON.stringify(body) });
}

export function updateRole(msId: number, roleId: number, patch: Partial<Pick<StaffRole, "name" | "granted_actions">>) {
  return staffRequest<StaffRole>(`/admin/makerspaces/${msId}/roles/${roleId}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteRole(msId: number, roleId: number) {
  return staffRequest<void>(`/admin/makerspaces/${msId}/roles/${roleId}`, { method: "DELETE" });
}

export type MachineScopeOption = {
  id: number;
  label: string;
  is_builtin?: boolean;
  is_active?: boolean;
};

export type RoleMachineScope = {
  machine_type_ids: number[];
  machine_ids: number[];
  available_machine_types: MachineScopeOption[];
  available_machines: MachineScopeOption[];
  /** False when the role is exempt (holds manage_makerspace) or grants no machine authority. */
  scoping_applies: boolean;
};

export function getRoleMachineScope(msId: number, roleId: number) {
  return staffRequest<RoleMachineScope>(`/admin/makerspaces/${msId}/roles/${roleId}/machine-scope`);
}

export function setRoleMachineScope(
  msId: number,
  roleId: number,
  body: { machine_type_ids: number[]; machine_ids: number[] },
) {
  return staffRequest<RoleMachineScope>(`/admin/makerspaces/${msId}/roles/${roleId}/machine-scope`, {
    method: "PUT", body: JSON.stringify(body),
  });
}

export function listCapabilities(msId: number) {
  return staffRequest<Capability[]>(`/admin/makerspaces/${msId}/roles/capabilities`);
}

export function listMemberships(msId: number) {
  return staffRequest<StaffMembershipRow[]>(`/admin/makerspaces/${msId}/memberships`);
}

export function createMembership(msId: number, body: {
  username: string; email?: string; first_name?: string; last_name?: string; password?: string; role_id: number;
}) {
  return staffRequest<StaffMembershipRow>(`/admin/makerspaces/${msId}/memberships`, { method: "POST", body: JSON.stringify(body) });
}

export function assignRole(msId: number, membershipId: number, roleId: number) {
  return staffRequest<StaffMembershipRow>(`/admin/makerspaces/${msId}/memberships/${membershipId}/role`, {
    method: "PATCH", body: JSON.stringify({ role_id: roleId }),
  });
}