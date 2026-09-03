import { useState } from "react";

import { EmptyState, SkeletonRows, StatusBadge } from "../../../components/ui";
import { EventDrawer } from "../EventsPanel";
import {
  useOrganizedEvents,
  type EventAdmin,
} from "../organizedEventsApi";
import { Panel } from "./shared";

const PAGE_SIZE = 50;

type SelectedEvent = Pick<EventAdmin, "id" | "makerspace_id">;

export function OrganizedEventsPanel() {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<SelectedEvent | null>(null);
  const events = useOrganizedEvents(page, PAGE_SIZE);
  const rows = events.data?.results ?? [];
  const totalPages = Math.max(1, Math.ceil((events.data?.count ?? 0) / PAGE_SIZE));

  return (
    <Panel title="Organized events">
      <p className="mb-3 text-sm text-muted">
        Events managed through your active organization roles, across every host makerspace.
      </p>

      {events.isLoading ? <OrganizedEventsTableSkeleton /> : null}
      {events.error ? (
        <EmptyState
          title="Unable to load organized events"
          description={events.error instanceof Error ? events.error.message : "Something went wrong."}
          action={(
            <button className="desk-button" type="button" onClick={() => events.refetch()}>
              Retry
            </button>
          )}
        />
      ) : null}
      {!events.isLoading && !events.error && !rows.length ? (
        <EmptyState title="No organized events -- this account has no active organization-managed events." />
      ) : null}

      {rows.length ? (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-[900px] divide-y divide-line text-left text-sm">
            <caption className="sr-only">Organization-managed events in chronological order</caption>
            <thead className="eyebrow bg-bg">
              <tr>
                <th scope="col" className="px-3 py-2">Title</th>
                <th scope="col" className="px-3 py-2">Date / location</th>
                <th scope="col" className="px-3 py-2">Status</th>
                <th scope="col" className="px-3 py-2">Registration totals</th>
                <th scope="col" className="px-3 py-2">Organizers</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-surface">
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="px-3 py-2 align-top">
                    <button
                      className="desk-button-ghost h-auto max-w-56 justify-start px-0 text-left"
                      type="button"
                      onClick={() => setSelected({ id: row.id, makerspace_id: row.makerspace_id })}
                    >
                      {row.title}
                    </button>
                  </td>
                  <td className="px-3 py-2 align-top text-muted">
                    <span className="block whitespace-nowrap">{formatDateRange(row)}</span>
                    <span className="mt-1 block max-w-56 break-words">{row.location || "No location"}</span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 align-top">
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="px-3 py-2 align-top">
                    <RegistrationTotals event={row} />
                  </td>
                  <td className="px-3 py-2 align-top">
                    {row.organizers.length ? (
                      <ul className="space-y-1">
                        {row.organizers.map((organizer) => (
                          <li key={organizer.slug}>
                            <span className="font-medium text-ink">{organizer.name}</span>{" "}
                            <span className="font-mono text-xs text-muted">({organizer.slug})</span>
                          </li>
                        ))}
                      </ul>
                    ) : <span className="text-muted">-</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {events.data ? (
        <div className="mt-3 flex items-center justify-between gap-3 text-sm">
          <button className="desk-button-ghost" type="button" disabled={!events.data.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>
            Previous
          </button>
          <span className="font-mono text-muted">Page {page} of {totalPages}</span>
          <button className="desk-button-ghost" type="button" disabled={!events.data.next} onClick={() => setPage((current) => current + 1)}>
            Next
          </button>
        </div>
      ) : null}

      {selected ? (
        <EventDrawer
          key={selected.id}
          eventId={selected.id}
          makerspaceId={selected.makerspace_id}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </Panel>
  );
}

function RegistrationTotals({ event }: { event: EventAdmin }) {
  const counts = event.registration_counts as typeof event.registration_counts & {
    pending_approval?: number;
    rejected?: number;
  };
  const pending = counts.pending_approval ?? 0;
  const rejected = counts.rejected ?? 0;
  const total = counts.registered + counts.attended + counts.waitlisted + counts.cancelled + pending + rejected;
  return (
    <div className="font-mono text-xs text-muted">
      <span className="block text-sm font-medium text-ink">{total} total</span>
      <span className="block">{counts.registered} registered · {counts.attended} attended</span>
      <span className="block">{counts.waitlisted} waitlisted · {counts.cancelled} cancelled</span>
      <span className="block">{pending} pending · {rejected} rejected</span>
    </div>
  );
}

function OrganizedEventsTableSkeleton() {
  return (
    <div className="overflow-x-auto rounded-md border border-line" aria-label="Loading organized events">
      <table className="min-w-[900px] divide-y divide-line text-left text-sm">
        <thead className="eyebrow bg-bg">
          <tr>
            {["Title", "Date / location", "Status", "Registration totals", "Organizers"].map((label) => (
              <th scope="col" key={label} className="px-3 py-2">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          <SkeletonRows rows={4} cols={5} />
        </tbody>
      </table>
    </div>
  );
}

function formatDateRange(event: Pick<EventAdmin, "starts_at" | "ends_at">) {
  const start = new Date(event.starts_at);
  const end = new Date(event.ends_at);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Date unavailable";
  return `${start.toLocaleString()} - ${end.toLocaleString()}`;
}
