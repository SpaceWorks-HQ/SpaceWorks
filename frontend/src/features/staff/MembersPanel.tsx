import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "../../components/ui";
import type {
  AdminMembership,
  MembershipRequest,
  PaginatedAdminMembershipList,
  PaginatedMembershipRequestList,
  PatchedMembershipCapabilities,
} from "../../generated/api";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { Panel } from "./panels/shared";
import { PaymentReconcileActions } from "./PaymentReconcileActions";

type Presence = { display_name: string; role_label: string; started_at: string; expires_at: string };
type Role = { id: number; name: string };

export const membershipErrorText = (error: unknown) =>
  error instanceof StructuredApiError ? error.detail ?? error.message : "Unable to update membership.";

// `membership` gates the COMMUNITY side only. The staff roster, role assignment and
// revoke are core RBAC state and are never gated -- gating them would let a makerspace
// lock itself out of its own administration (plan A7). So the module hides exactly the
// surfaces the backend refuses: the request queue, the waiver, and the verification /
// referral capabilities. Invitation stays, because a STAFF invitation keeps working with
// the module off (`invite_membership` discriminates on the role's granted actions).
export function MembersPanel({ makerspaceId, membershipEnabled }: { makerspaceId: number; membershipEnabled: boolean }) {
  const client = useQueryClient();
  const key = ["members", makerspaceId];
  const roster = useQuery({
    queryKey: [...key, "roster"],
    queryFn: () => staffRequest<PaginatedAdminMembershipList>(`/admin/memberships?makerspace_id=${makerspaceId}`),
  });
  const requests = useQuery({
    queryKey: [...key, "requests"],
    queryFn: () => staffRequest<PaginatedMembershipRequestList>(`/admin/membership-requests?makerspace_id=${makerspaceId}`),
    enabled: membershipEnabled,
  });
  const presence = useQuery({ queryKey: [...key, "presence"], queryFn: () => staffRequest<Presence[]>(`/admin/makerspace/${makerspaceId}/presence-sessions/current`) });
  const roles = useQuery({ queryKey: [...key, "roles"], queryFn: () => staffRequest<Role[]>(`/admin/makerspaces/${makerspaceId}/roles`) });
  const [roleId, setRoleId] = useState<number | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [waiver, setWaiver] = useState({ version: "", body: "" });
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const revoke = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/memberships/${id}/revoke`, { method: "POST", body: JSON.stringify({}) }), onSuccess: refresh });
  const revokeRequest = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/membership-requests/${id}/revoke`, { method: "POST", body: JSON.stringify({}) }), onSuccess: refresh });
  const approve = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/membership-requests/${id}/approve`, { method: "POST", body: JSON.stringify({ role_id: roleId }) }), onSuccess: refresh });
  const changeRole = useMutation({ mutationFn: ({ id, nextRoleId }: { id: number; nextRoleId: number }) => staffRequest(`/admin/memberships/${id}/role`, { method: "PATCH", body: JSON.stringify({ role_id: nextRoleId }) }), onSuccess: refresh });
  const capabilities = useMutation({
    mutationFn: ({ id, next }: { id: number; next: PatchedMembershipCapabilities }) =>
      staffRequest<AdminMembership>(`/admin/memberships/${id}/capabilities`, {
        method: "PATCH",
        body: JSON.stringify(next),
      }),
    onSuccess: refresh,
  });
  const verify = useMutation({
    mutationFn: ({ id, verified }: { id: number; verified: boolean }) =>
      staffRequest<AdminMembership>(`/admin/memberships/${id}/${verified ? "verify" : "unverify"}`, {
        method: "POST",
      }),
    onSuccess: refresh,
  });
  const invite = useMutation({ mutationFn: () => staffRequest(`/admin/makerspace/${makerspaceId}/membership-invitations`, { method: "POST", body: JSON.stringify({ invite_email: inviteEmail, role_id: roleId }) }), onSuccess: () => { setInviteEmail(""); refresh(); } });
  const publishWaiver = useMutation({ mutationFn: () => staffRequest(`/admin/makerspaces/${makerspaceId}/waiver`, { method: "PUT", body: JSON.stringify(waiver) }), onSuccess: refresh });
  const error = revoke.error ?? revokeRequest.error ?? approve.error ?? changeRole.error ?? capabilities.error ?? verify.error ?? invite.error ?? publishWaiver.error;
  const selectedRole = roleId ?? roles.data?.[0]?.id ?? null;
  const rosterRows = roster.data?.results ?? [];
  const requestRows = requests.data?.results ?? [];

  return <div className="grid gap-5">
    <Panel title="Members">
      <p className="mb-4 text-sm text-muted">Membership, referral and verification delegation, waiver compliance, and active presence for this makerspace.</p>
      {rosterRows.map((row) => <MemberRow
        key={row.id}
        makerspaceId={makerspaceId}
        member={row}
        roles={roles.data ?? []}
        changingRole={changeRole.isPending}
        changingCapabilities={capabilities.isPending}
        changingVerification={verify.isPending}
        onChangeRole={(nextRoleId) => changeRole.mutate({ id: row.id, nextRoleId })}
        membershipEnabled={membershipEnabled}
        onCapability={(next) => capabilities.mutate({ id: row.id, next })}
        onVerify={() => verify.mutate({ id: row.id, verified: !Boolean(row.verified_at) })}
        onRevoke={() => revoke.mutate(row.id)}
      />)}
      {roster.isLoading ? <p className="text-sm text-muted">Loading members…</p> : null}
      {roster.isError ? <p className="text-sm text-danger" role="alert">{membershipErrorText(roster.error)}</p> : null}
    </Panel>
    <Panel title={membershipEnabled ? "Membership requests" : "Invitations"}><div className="mb-3 flex flex-wrap gap-2"><select className="desk-input" value={selectedRole ?? ""} onChange={(event) => setRoleId(Number(event.target.value))}>{roles.data?.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select><input className="desk-input" type="email" placeholder="Invite email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} /><button className="desk-button" disabled={!inviteEmail || !selectedRole || invite.isPending} onClick={() => invite.mutate()}>Invite</button></div>
      {membershipEnabled ? requestRows.map((row) => <div className="flex items-center justify-between gap-3 border-t border-line py-3" key={row.id}><span className="text-sm text-ink">{requestLabel(row)} · {row.kind} · {row.state}</span>{row.state === "requested" ? <div className="flex gap-2"><button className="desk-button-primary" disabled={!selectedRole || approve.isPending} onClick={() => approve.mutate(row.id)}>Approve</button><button className="desk-button" onClick={() => revokeRequest.mutate(row.id)} disabled={revokeRequest.isPending}>Revoke</button></div> : null}</div>) : null}
      {membershipEnabled && requests.isLoading ? <p className="text-sm text-muted">Loading requests…</p> : null}</Panel>
    <Panel title="Currently present">{presence.data?.length ? presence.data.map((row) => <p className="border-t border-line py-2 text-sm text-ink" key={`${row.display_name}-${row.started_at}`}>{row.display_name} <span className="text-muted">· {row.role_label} · until {new Date(row.expires_at).toLocaleTimeString()}</span></p>) : <p className="text-sm text-muted">No active member presence sessions.</p>}</Panel>
    {membershipEnabled ? <Panel title="Current waiver"><div className="grid gap-2"><input className="desk-input" placeholder="Version" value={waiver.version} onChange={(event) => setWaiver({ ...waiver, version: event.target.value })} /><textarea className="desk-input min-h-28" placeholder="Waiver text" value={waiver.body} onChange={(event) => setWaiver({ ...waiver, body: event.target.value })} /><button className="desk-button-primary w-fit" disabled={!waiver.version || !waiver.body || publishWaiver.isPending} onClick={() => publishWaiver.mutate()}>Publish waiver</button></div></Panel> : null}
    {error ? <p className="text-sm text-danger" role="alert">{membershipErrorText(error)}</p> : null}
  </div>;
}

function MemberRow({ makerspaceId, member, roles, membershipEnabled, changingRole, changingCapabilities, changingVerification, onChangeRole, onCapability, onVerify, onRevoke }: {
  makerspaceId: number;
  member: AdminMembership;
  roles: Role[];
  membershipEnabled: boolean;
  changingRole: boolean;
  changingCapabilities: boolean;
  changingVerification: boolean;
  onChangeRole: (roleId: number) => void;
  onCapability: (next: PatchedMembershipCapabilities) => void;
  onVerify: () => void;
  onRevoke: () => void;
}) {
  const active = member.status === "active";
  const displayName = member.user.display_name || member.user.username;
  return <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line py-3">
    <div><p className="font-semibold text-ink">{displayName}</p><p className="text-xs text-muted">{member.assigned_role?.name ?? "Member"} · {member.status} · waiver {member.waiver_current ? "current" : "needed"}</p><PaymentReconcileActions makerspaceId={makerspaceId} payment={member.payment} invalidateKeys={[["members", makerspaceId]]} /></div>
    <div className="flex flex-wrap items-center gap-2">
      {membershipEnabled ? <Badge tone={member.verified_at ? "success" : "neutral"}>{member.verified_at ? "Verified" : "Not verified"}</Badge> : null}
      {active ? <>{membershipEnabled ? <><label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={member.can_refer} disabled={changingCapabilities} onChange={(event) => onCapability({ can_refer: event.target.checked })} />Can refer</label><label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={member.can_verify} disabled={changingCapabilities} onChange={(event) => onCapability({ can_verify: event.target.checked })} />Can verify</label><button className="desk-button" type="button" disabled={changingVerification} onClick={onVerify}>{member.verified_at ? "Unverify" : "Verify"}</button></> : null}<select className="desk-input" defaultValue={member.assigned_role?.id ?? ""} onChange={(event) => onChangeRole(Number(event.target.value))} disabled={changingRole}>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select><button className="desk-button" type="button" onClick={onRevoke}>Revoke</button></> : null}
    </div>
  </div>;
}

function requestLabel(request: MembershipRequest) {
  return request.user?.username ?? request.invite_email;
}
