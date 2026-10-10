import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, Field } from "../../components/ui";
import type {
  AdminMembership,
  MembershipRequest,
  PaginatedAdminMembershipList,
  PaginatedMembershipRequestList,
  PatchedMembershipCapabilities,
} from "../../generated/api";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { InvitationRequestsSection } from "./InvitationRequestsSection";
import { MembershipPlansSection } from "./MembershipPlansSection";
import { MemberTermsDialog } from "./MemberTermsDialog";
import { Panel } from "./panels/shared";
import { PaymentReconcileActions } from "./PaymentReconcileActions";
import { MembershipReasonDialog } from "./MembershipReasonDialog";
import { MembershipPagination } from "./MembershipPagination";
import { MembershipPlanPicker } from "./MembershipPlanPicker";
import { MembershipWaiverPanel } from "./MembershipWaiverPanel";

type Presence = { display_name: string; role_label: string; started_at: string; expires_at: string };
type Role = { id: number; name: string };

export const membershipErrorText = (error: unknown) =>
  error instanceof StructuredApiError ? error.detail ?? error.message : "Unable to update membership.";

// `membership` gates the COMMUNITY side only. The staff roster, role assignment and
// revoke are core RBAC state and are never gated -- gating them would let a makerspace
// lock itself out of its own administration (plan A7). So the module hides exactly the
// surfaces the backend refuses: the request queue and verification/referral capabilities.
// Waiver management and witnessed acceptance are core liability controls. Invitation stays,
// because a STAFF invitation keeps working with
// the module off (`invite_membership` discriminates on the role's granted actions).
export function MembersPanel({ makerspaceId, membershipEnabled }: { makerspaceId: number; membershipEnabled: boolean }) {
  const client = useQueryClient();
  const key = ["members", makerspaceId];
  const [rosterPage, setRosterPage] = useState(1);
  const [requestPage, setRequestPage] = useState(1);
  const [planId, setPlanId] = useState<number | null>(null);
  const [decision, setDecision] = useState<{ id: number; kind: "member" | "request"; title: string } | null>(null);
  const roster = useQuery({
    queryKey: [...key, "roster", rosterPage],
    queryFn: () => staffRequest<PaginatedAdminMembershipList>(`/admin/memberships?makerspace_id=${makerspaceId}&page=${rosterPage}`),
  });
  const requests = useQuery({
    queryKey: [...key, "requests", requestPage, membershipEnabled],
    // Not gated on the module: with it off the backend still lists STAFF invitations
    // (and only those), which staff must be able to approve or cancel.
    queryFn: () => staffRequest<PaginatedMembershipRequestList>(`/admin/membership-requests?makerspace_id=${makerspaceId}&page=${requestPage}`),
  });
  const presence = useQuery({ queryKey: [...key, "presence"], queryFn: () => staffRequest<Presence[]>(`/admin/makerspace/${makerspaceId}/presence-sessions/current`) });
  const roles = useQuery({ queryKey: [...key, "roles"], queryFn: () => staffRequest<Role[]>(`/admin/makerspaces/${makerspaceId}/roles`) });
  const [roleId, setRoleId] = useState<number | null>(null);
  // What the dropdown SHOWS: the first role until staff pick another. Approve and Invite
  // must post this, not `roleId` -- that stays null until a change event, so with one role
  // (or the default left alone) both used to send `role_id: null` and fail.
  const selectedRole = roleId ?? roles.data?.[0]?.id ?? null;
  const [inviteEmail, setInviteEmail] = useState("");
  const [termsMember, setTermsMember] = useState<AdminMembership | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const decisionSaved = () => { setDecision(null); void refresh(); };
  const revoke = useMutation({ mutationFn: ({ id, reason }: { id: number; reason: string }) => staffRequest(`/admin/memberships/${id}/revoke`, { method: "POST", body: JSON.stringify({ reason }) }), onSuccess: decisionSaved });
  const revokeRequest = useMutation({ mutationFn: ({ id, reason }: { id: number; reason: string }) => staffRequest(`/admin/membership-requests/${id}/revoke`, { method: "POST", body: JSON.stringify({ reason }) }), onSuccess: decisionSaved });
  const approve = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/membership-requests/${id}/approve`, { method: "POST", body: JSON.stringify({ role_id: selectedRole, ...(membershipEnabled && planId ? { plan_id: planId } : {}) }) }), onSuccess: refresh });
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
  const invite = useMutation({ mutationFn: () => staffRequest(`/admin/makerspace/${makerspaceId}/membership-invitations`, { method: "POST", body: JSON.stringify({ invite_email: inviteEmail, role_id: selectedRole }) }), onSuccess: () => { setInviteEmail(""); refresh(); } });
  const witnessWaiver = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/memberships/${id}/waiver/witness`, { method: "POST", body: JSON.stringify({}) }), onSuccess: refresh });
  const error = revoke.error ?? revokeRequest.error ?? approve.error ?? changeRole.error ?? capabilities.error ?? verify.error ?? invite.error ?? witnessWaiver.error;
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
        changingWitness={witnessWaiver.isPending}
        onChangeRole={(nextRoleId) => changeRole.mutate({ id: row.id, nextRoleId })}
        membershipEnabled={membershipEnabled}
        onCapability={(next) => capabilities.mutate({ id: row.id, next })}
        onVerify={() => verify.mutate({ id: row.id, verified: !Boolean(row.verified_at) })}
        onWitness={() => witnessWaiver.mutate(row.id)}
        onRevoke={() => { revoke.reset(); setDecision({ id: row.id, kind: "member", title: `Revoke ${row.user.display_name || row.user.username}` }); }}
        onTerms={() => setTermsMember(row)}
      />)}
      {roster.isLoading ? <p className="text-sm text-muted">Loading members…</p> : null}
      {roster.isError ? <p className="text-sm text-danger" role="alert">{membershipErrorText(roster.error)}</p> : null}
      {roster.isSuccess && !rosterRows.length ? <p className="text-sm text-muted">No members on this page.</p> : null}
      <MembershipPagination label="members" page={rosterPage} next={roster.data?.next} previous={roster.data?.previous} fetching={roster.isFetching} onPage={setRosterPage} />
    </Panel>
    <Panel title={membershipEnabled ? "Membership requests" : "Invitations"}><div className="mb-3 flex flex-wrap gap-2"><Field label="Invite role"><select className="desk-input" value={selectedRole ?? ""} onChange={(event) => setRoleId(Number(event.target.value))}>{roles.data?.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></Field><Field label="Invite email"><input className="desk-input" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} /></Field><button className="desk-button" disabled={!inviteEmail || !selectedRole || invite.isPending} onClick={() => invite.mutate()}>Invite</button></div>
      {roles.isError ? <p role="alert" className="text-sm text-danger">{membershipErrorText(roles.error)}</p> : null}
      {membershipEnabled ? <MembershipPlanPicker makerspaceId={makerspaceId} value={planId} onChange={setPlanId} /> : null}
      {requestRows.map((row) => <div className="flex items-center justify-between gap-3 border-t border-line py-3" key={row.id}><span className="text-sm text-ink">{requestLabel(row)} · {row.kind} · {row.state}</span>{row.state === "requested" || row.state === "invited" ? <div className="flex gap-2">{row.state === "requested" || row.user ? <button className="desk-button-primary" disabled={!selectedRole || approve.isPending} onClick={() => approve.mutate(row.id)}>Approve</button> : null}<button className="desk-button" onClick={() => { revokeRequest.reset(); setDecision({ id: row.id, kind: "request", title: row.state === "invited" ? "Cancel invitation" : "Decline membership request" }); }} disabled={revokeRequest.isPending}>{row.state === "invited" ? "Cancel invitation" : "Decline"}</button></div> : null}</div>)}
      {requests.isLoading ? <p className="text-sm text-muted">Loading requests…</p> : null}
      {requests.isError ? <p role="alert" className="text-sm text-danger">{membershipErrorText(requests.error)}</p> : null}
      {requests.isSuccess && !requestRows.length ? <p className="text-sm text-muted">No membership requests on this page.</p> : null}
      <MembershipPagination label="requests" page={requestPage} next={requests.data?.next} previous={requests.data?.previous} fetching={requests.isFetching} onPage={setRequestPage} /></Panel>
    {membershipEnabled ? <InvitationRequestsSection makerspaceId={makerspaceId} roles={roles.data ?? []} /> : null}
    {membershipEnabled ? <MembershipPlansSection makerspaceId={makerspaceId} /> : null}
    <Panel title="Currently present">{presence.data?.length ? presence.data.map((row) => <p className="border-t border-line py-2 text-sm text-ink" key={`${row.display_name}-${row.started_at}`}>{row.display_name} <span className="text-muted">· {row.role_label} · until {new Date(row.expires_at).toLocaleTimeString()}</span></p>) : <p className="text-sm text-muted">No active member presence sessions.</p>}</Panel>
    <MembershipWaiverPanel makerspaceId={makerspaceId} />
    {error ? <p className="text-sm text-danger" role="alert">{membershipErrorText(error)}</p> : null}
    {decision ? <MembershipReasonDialog key={`${decision.kind}-${decision.id}`} title={decision.title} pending={revoke.isPending || revokeRequest.isPending} error={(decision.kind === "member" ? revoke.error : revokeRequest.error) ? membershipErrorText(decision.kind === "member" ? revoke.error : revokeRequest.error) : null} onClose={() => setDecision(null)} onConfirm={(reason) => (decision.kind === "member" ? revoke : revokeRequest).mutate({ id: decision.id, reason })} /> : null}
    {termsMember ? <MemberTermsDialog key={termsMember.id} makerspaceId={makerspaceId} membershipId={termsMember.id} memberName={termsMember.user.display_name || termsMember.user.username} onClose={() => setTermsMember(null)} /> : null}
  </div>;
}

function MemberRow({ makerspaceId, member, roles, membershipEnabled, changingRole, changingCapabilities, changingVerification, changingWitness, onChangeRole, onCapability, onVerify, onWitness, onRevoke, onTerms }: {
  makerspaceId: number;
  member: AdminMembership;
  roles: Role[];
  membershipEnabled: boolean;
  changingRole: boolean;
  changingCapabilities: boolean;
  changingVerification: boolean;
  changingWitness: boolean;
  onChangeRole: (roleId: number) => void;
  onCapability: (next: PatchedMembershipCapabilities) => void;
  onVerify: () => void;
  onWitness: () => void;
  onRevoke: () => void;
  onTerms: () => void;
}) {
  const active = member.status === "active";
  const displayName = member.user.display_name || member.user.username;
  return <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line py-3">
    <div><p className="font-semibold text-ink">{displayName}</p><p className="text-xs text-muted">{member.assigned_role?.name ?? "Member"} · {member.status} · waiver {member.waiver_required ? (member.waiver_current ? "current" : "needed") : "not required"}</p><PaymentReconcileActions makerspaceId={makerspaceId} payment={member.payment} invalidateKeys={[["members", makerspaceId]]} /></div>
    <div className="flex flex-wrap items-center gap-2">
      {membershipEnabled ? <Badge tone={member.verified_at ? "success" : "neutral"}>{member.verified_at ? "Verified" : "Not verified"}</Badge> : null}
      {active ? <>{member.waiver_required && !member.waiver_current ? <button className="desk-button" type="button" disabled={changingWitness} onClick={onWitness}>Record witnessed acceptance</button> : null}{membershipEnabled ? <><label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={member.can_refer} disabled={changingCapabilities} onChange={(event) => onCapability({ can_refer: event.target.checked })} />Can refer</label><label className="flex items-center gap-1 text-xs text-muted"><input type="checkbox" checked={member.can_verify} disabled={changingCapabilities} onChange={(event) => onCapability({ can_verify: event.target.checked })} />Can verify</label><button className="desk-button" type="button" disabled={changingVerification} onClick={onVerify}>{member.verified_at ? "Unverify" : "Verify"}</button><button className="desk-button" type="button" onClick={onTerms}>Terms</button></> : null}<select aria-label={`Role for ${displayName}`} className="desk-input" defaultValue={member.assigned_role?.id ?? ""} onChange={(event) => onChangeRole(Number(event.target.value))} disabled={changingRole}>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select><button className="desk-button" type="button" onClick={onRevoke}>Revoke</button></> : null}
    </div>
  </div>;
}

function requestLabel(request: MembershipRequest) {
  return request.user?.username ?? request.invite_email;
}
