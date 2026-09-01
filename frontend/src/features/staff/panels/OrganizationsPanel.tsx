import { useEffect, useState } from "react";

import { EmptyState, Skeleton } from "../../../components/ui";
import { OrganizationInvitations } from "../OrganizationInvitations";
import { OrganizationMemberships } from "../OrganizationMemberships";
import { OrganizationProfileForm } from "../OrganizationProfileForm";
import { useOrganization, useOrganizations } from "../organizationsApi";
import { Panel } from "./shared";

export function OrganizationsPanel() {
  const [page, setPage] = useState(1);
  const organizations = useOrganizations(page);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const detail = useOrganization(selectedId);

  useEffect(() => {
    if (selectedId === null && organizations.data?.results[0]) {
      setSelectedId(organizations.data.results[0].id);
    }
  }, [organizations.data, selectedId]);

  return (
    <Panel title="Organizations">
      <p className="mb-4 text-sm text-muted">Manage public organization presentation, delegated governance, and single-use invitations.</p>
      {organizations.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {organizations.error ? <EmptyState title="Unable to load organizations" description={organizations.error.message} action={<button className="desk-button" type="button" onClick={() => organizations.refetch()}>Retry</button>} /> : null}
      {organizations.data && !organizations.data.results.length ? <EmptyState title="No organization access" description="This account does not have an active organization membership." /> : null}
      {organizations.data?.results.length ? (
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <label className="grid min-w-64 flex-1 gap-1 text-sm font-semibold">Organization
            <select className="desk-input" value={selectedId ?? ""} onChange={(event) => setSelectedId(Number(event.target.value))}>
              {organizations.data.results.map((organization) => <option key={organization.id} value={organization.id}>{organization.name}</option>)}
            </select>
          </label>
          <button className="desk-button" type="button" disabled={!organizations.data.previous} onClick={() => { setSelectedId(null); setPage((value) => Math.max(1, value - 1)); }}>Previous</button>
          <button className="desk-button" type="button" disabled={!organizations.data.next} onClick={() => { setSelectedId(null); setPage((value) => value + 1); }}>Next</button>
        </div>
      ) : null}
      {detail.isLoading ? <Skeleton className="h-56 w-full" /> : null}
      {detail.error ? <EmptyState title="Unable to load organization" description={detail.error.message} /> : null}
      {detail.data ? <div className="grid gap-5"><OrganizationProfileForm organization={detail.data} /><OrganizationMemberships organization={detail.data} /><OrganizationInvitations organization={detail.data} /></div> : null}
    </Panel>
  );
}
