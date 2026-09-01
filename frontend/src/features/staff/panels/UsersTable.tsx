import { useEffect, useState } from "react";

import { Badge, EmptyState, Modal } from "../../../components/ui";
import type { StaffMembershipRow, StaffRole } from "./rolesApi";

export function UsersTable({ rows, makerspaceNames, loading, assignableRoles, onRestrict, onRestore, onResetPassword, onRevoke, onChangeRole }: {
  rows: StaffMembershipRow[];
  makerspaceNames: Map<number, string>;
  loading: boolean;
  assignableRoles: StaffRole[];
  onRestrict: (membership: StaffMembershipRow) => void;
  onRestore: (membership: StaffMembershipRow) => void;
  onResetPassword: (membership: StaffMembershipRow) => void;
  onRevoke: (membership: StaffMembershipRow) => void;
  onChangeRole: (membership: StaffMembershipRow, roleId: number) => Promise<unknown>;
}) {
  const [changeTarget, setChangeTarget] = useState<StaffMembershipRow | null>(null);
  const [roleId, setRoleId] = useState<number | "">("");
  const [assignPending, setAssignPending] = useState(false);
  const [assignError, setAssignError] = useState("");
  const openChange = (membership: StaffMembershipRow) => {
    setAssignError("");
    setChangeTarget(membership);
    setRoleId(membership.assigned_role?.id ?? "");
  };
  const submitChange = () => {
    if (!changeTarget || roleId === "") return;
    setAssignError("");
    setAssignPending(true);
    onChangeRole(changeTarget, roleId)
      .then(() => setChangeTarget(null))
      .catch((error) => setAssignError(error instanceof Error ? error.message : "Unable to change role"))
      .finally(() => setAssignPending(false));
  };
  if (loading) return <p className="text-sm text-muted">Loading staff...</p>;
  if (!rows.length) return <EmptyState title="No staff" description="No memberships match this filter." />;
  return (
    <>
      <div className="overflow-x-auto rounded-md border border-line bg-bg">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="eyebrow bg-surface"><tr className="border-b border-line">{["Username", "Email", "Role", "Makerspace", "Access", ""].map((header) => <th scope={header ? "col" : undefined} key={header} className="px-3 py-2">{header}</th>)}</tr></thead>
          <tbody>{rows.map((membership) => <tr key={membership.id} className="border-b border-line last:border-b-0">
            <td className="px-3 py-2 font-semibold text-ink"><span className="block max-w-40 break-words">{membership.user.username}</span></td>
            <td className="px-3 py-2 text-muted"><span className="block max-w-56 break-all">{membership.user.email || "-"}</span></td>
            <td className="px-3 py-2 text-ink">{roleLabel(membership)}</td>
            <td className="px-3 py-2 text-ink">{makerspaceNames.get(membership.makerspace_id) ?? membership.makerspace_slug}</td>
            <td className="px-3 py-2"><AccessBadge status={membership.user.access_status} /></td>
            <td className="px-3 py-2"><div className="desk-actions flex flex-wrap justify-end gap-2">
              <button className="desk-button-ghost" type="button" disabled={!assignableRoles.length} onClick={() => openChange(membership)}>Change role</button>
              <button className="desk-button-danger" type="button" onClick={() => onRestrict(membership)}>Restrict</button>
              <button className="desk-button-warn" type="button" onClick={() => onResetPassword(membership)}>Reset password</button>
              <button className="desk-button-success" type="button" disabled={membership.user.access_status === "active"} onClick={() => onRestore(membership)}>Restore</button>
              <button className="desk-button-danger" type="button" onClick={() => onRevoke(membership)}>Revoke</button>
            </div></td>
          </tr>)}</tbody>
        </table>
      </div>
      <ChangeRoleModal target={changeTarget} roleId={roleId} roles={assignableRoles} pending={assignPending} error={assignError} onClose={() => setChangeTarget(null)} onChange={setRoleId} onSubmit={submitChange} />
    </>
  );
}

function ChangeRoleModal({ target, roleId, roles, pending, error, onClose, onChange, onSubmit }: {
  target: StaffMembershipRow | null;
  roleId: number | "";
  roles: StaffRole[];
  pending: boolean;
  error: string;
  onClose: () => void;
  onChange: (roleId: number) => void;
  onSubmit: () => void;
}) {
  useEffect(() => { if (target && roleId === "" && roles[0]) onChange(roles[0].id); }, [target, roleId, roles, onChange]);
  return <Modal open={Boolean(target)} onClose={onClose} title={target ? `Change role for ${target.user.username}` : "Change role"} footer={<div className="desk-actions flex justify-end gap-2"><button className="desk-button-ghost" type="button" disabled={pending} onClick={onClose}>Cancel</button><button className="desk-button-primary" type="button" disabled={roleId === "" || pending} onClick={onSubmit}>{pending ? "Saving..." : "Save role"}</button></div>}><div className="grid gap-2"><label className="grid gap-1"><span className="eyebrow">Role</span><select className="desk-input w-full" value={roleId} onChange={(event) => onChange(Number(event.target.value))}>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>{error ? <p className="text-sm text-danger">{error}</p> : null}</div></Modal>;
}

function AccessBadge({ status }: { status: string }) {
  const tone = status === "active" ? "success" : status === "restricted" ? "warn" : "danger";
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

function roleLabel(membership: StaffMembershipRow) {
  return membership.assigned_role?.name ?? membership.role.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
