import { useState, type FormEvent } from "react";

import { EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import type { OrganizationDetail } from "./organizationsApi";
import {
  useCreateOrganizationInvitation,
  useOrganizationInvitations,
  useRevokeOrganizationInvitation,
} from "./organizationsApi";

function toggle(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function OrganizationInvitations({ organization }: { organization: OrganizationDetail }) {
  const [page, setPage] = useState(1);
  const [governanceActions, setGovernanceActions] = useState<string[]>([]);
  const [grantedActions, setGrantedActions] = useState<string[]>([]);
  const [expiresInDays, setExpiresInDays] = useState(7);
  const [rawToken, setRawToken] = useState<string | null>(null);
  const allowed = organization.governance_actions.includes("manage_organization_members");
  const invitations = useOrganizationInvitations(organization.id, page, allowed);
  const create = useCreateOrganizationInvitation(organization.id);
  const revoke = useRevokeOrganizationInvitation(organization.id);
  if (!allowed) return null;

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { governance_actions: governanceActions, granted_actions: grantedActions, expires_in_days: expiresInDays },
      { onSuccess: (invitation) => setRawToken(invitation.token) },
    );
  }

  const redeemUrl = rawToken ? `${window.location.origin}/organization-invitations/redeem/${rawToken}` : "";
  return (
    <section className="rounded-xl border border-line bg-bg p-4" aria-labelledby="organization-invitations-heading">
      <h3 className="title-section" id="organization-invitations-heading">Invitations</h3>
      <p className="mt-1 text-sm text-muted">Each bearer link works once. Its token is shown only after creation.</p>
      <form className="mt-4 grid gap-4" onSubmit={submit}>
        <fieldset><legend className="eyebrow mb-2">Organization governance</legend><div className="flex flex-wrap gap-3">
          {organization.governance_actions.map((action) => <label className="flex items-center gap-2 text-sm" key={action}><input type="checkbox" checked={governanceActions.includes(action)} onChange={() => setGovernanceActions(toggle(governanceActions, action))} />{action.split("_").join(" ")}</label>)}
        </div></fieldset>
        <fieldset><legend className="eyebrow mb-2">Makerspace actions</legend><div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {organization.granted_actions.map((action) => <label className="flex items-center gap-2 text-sm" key={action}><input type="checkbox" checked={grantedActions.includes(action)} onChange={() => setGrantedActions(toggle(grantedActions, action))} />{action.split("_").join(" ")}</label>)}
        </div></fieldset>
        <label className="grid max-w-48 gap-1 text-sm font-semibold">Expires in days<input className="desk-input" type="number" min="1" max="30" value={expiresInDays} onChange={(event) => setExpiresInDays(Number(event.target.value))} /></label>
        <button className="desk-button-primary w-fit" type="submit" disabled={create.isPending}>{create.isPending ? "Creating..." : "Create invitation"}</button>
        {create.error ? <p className="text-sm text-danger" role="alert">{create.error.message}</p> : null}
      </form>
      {redeemUrl ? <div className="mt-4 rounded-xl border border-success bg-success/15 p-4 text-success-ink"><p className="font-semibold">Copy this link now</p><p className="mt-1 break-all font-mono text-xs">{redeemUrl}</p><button className="desk-button mt-3" type="button" onClick={() => navigator.clipboard.writeText(redeemUrl)}>Copy link</button></div> : null}

      {invitations.isLoading ? <Skeleton className="mt-5 h-24 w-full" /> : null}
      {invitations.data && !invitations.data.results.length ? <EmptyState title="No invitations yet" /> : null}
      {invitations.data?.results.length ? <ul className="mt-5 divide-y divide-line rounded-lg border border-line bg-surface">{invitations.data.results.map((invitation) => (
        <li className="flex flex-wrap items-center justify-between gap-3 p-3" key={invitation.id}>
          <div><StatusBadge status={invitation.state} /><p className="mt-1 font-mono text-xs text-muted">Expires {new Date(invitation.expires_at).toLocaleString()}</p></div>
          {invitation.state === "active" ? <button className="desk-button-danger" type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(invitation.id)}>Revoke</button> : null}
        </li>
      ))}</ul> : null}
      {invitations.data ? <div className="mt-3 flex items-center justify-between gap-3"><button className="desk-button" type="button" disabled={!invitations.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><span className="font-mono text-xs text-muted">Page {page}</span><button className="desk-button" type="button" disabled={!invitations.data.next} onClick={() => setPage((value) => value + 1)}>Next</button></div> : null}
    </section>
  );
}
