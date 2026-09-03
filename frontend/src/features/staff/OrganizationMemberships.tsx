import { useState } from "react";

import { EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import type { OrganizationDetail } from "./organizationsApi";
import { useOrganizationMemberships } from "./organizationsApi";

export function OrganizationMemberships({ organization }: { organization: OrganizationDetail }) {
  const [page, setPage] = useState(1);
  const enabled = organization.governance_actions.includes("manage_organization_members");
  const memberships = useOrganizationMemberships(organization.id, page, enabled);
  if (!enabled) return null;

  return (
    <section className="rounded-xl border border-line bg-bg p-4" aria-labelledby="organization-members-heading">
      <h3 className="title-section" id="organization-members-heading">Memberships</h3>
      {memberships.isLoading ? <Skeleton className="mt-3 h-28 w-full" /> : null}
      {memberships.error ? <p className="mt-3 text-sm text-danger" role="alert">{memberships.error.message}</p> : null}
      {memberships.data && !memberships.data.results.length ? <EmptyState title="No organization members" /> : null}
      {memberships.data?.results.length ? (
        <div className="mt-3 overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[720px] text-left text-sm">
            <caption className="sr-only">Organization memberships</caption>
            <thead className="bg-surface"><tr><th className="eyebrow p-3" scope="col">Member</th><th className="eyebrow p-3" scope="col">Status</th><th className="eyebrow p-3" scope="col">Governance</th><th className="eyebrow p-3" scope="col">Makerspace actions</th></tr></thead>
            <tbody>{memberships.data.results.map((member) => (
              <tr className="border-t border-line" key={member.id}>
                <td className="p-3"><span className="font-semibold text-ink">{member.display_name || member.username}</span><span className="block text-xs text-muted">{member.email}</span></td>
                <td className="p-3"><StatusBadge status={member.status} /></td>
                <td className="p-3 font-mono text-xs text-muted">{member.governance_actions.join(", ") || "—"}</td>
                <td className="p-3 font-mono text-xs text-muted">{member.granted_actions.join(", ") || "—"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : null}
      {memberships.data ? (
        <div className="mt-3 flex items-center justify-between gap-3">
          <button className="desk-button" type="button" disabled={!memberships.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button>
          <span className="font-mono text-xs text-muted">Page {page} · {memberships.data.count} members</span>
          <button className="desk-button" type="button" disabled={!memberships.data.next} onClick={() => setPage((value) => value + 1)}>Next</button>
        </div>
      ) : null}
    </section>
  );
}
