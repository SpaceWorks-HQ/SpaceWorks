import { useState, type FormEvent } from "react";

import { EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { CollaborationInbox } from "./CollaborationInbox";
import { EventDrawer } from "./EventDrawer";
import { eventErrorText } from "./eventUi";
import {
  EventFields,
  emptyEventForm,
  payloadFor,
  type EventFormValues,
} from "./EventFormFields";
import { useCreateEvent, useEvents, type StaffEvent } from "./eventsApi";
import { Panel } from "./panels/shared";

export { EventDrawer };

function dateRange(event: StaffEvent) {
  return `${new Date(event.starts_at).toLocaleString()} – ${new Date(event.ends_at).toLocaleString()}`;
}

export function EventsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const events = useEvents(makerspaceId, page);
  const create = useCreateEvent(makerspaceId);
  const [values, setValues] = useState<EventFormValues>(emptyEventForm);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(payloadFor(values), {
      onSuccess: (created) => {
        setValues(emptyEventForm);
        setSelectedId(created.id);
      },
    });
  }

  const apiError = events.error instanceof StructuredApiError ? events.error : null;
  if (apiError?.status === 403) return <Panel title="Events"><EmptyState title="Permission required" description="Event management access is required." /></Panel>;
  if (apiError?.status === 400) return <Panel title="Events"><EmptyState title="Events module unavailable" description={apiError.message} /></Panel>;

  return <Panel title="Events">
    <p className="mb-4 text-sm text-muted">Create events, review applications, and record attendance.</p>
    <CollaborationInbox makerspaceId={makerspaceId} />
    <form className="mb-5 rounded-xl border border-line bg-bg p-4" onSubmit={submit}>
      <h3 className="title-section mb-3">Create draft event</h3>
      <EventFields values={values} setValues={setValues} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="desk-button-primary" type="submit" disabled={create.isPending}>{create.isPending ? "Creating..." : "Create event"}</button>
        {create.error ? <p className="text-sm text-danger" role="alert">{eventErrorText(create.error)}</p> : null}
      </div>
    </form>
    {events.isLoading ? <div className="grid gap-2" aria-label="Loading events">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div> : null}
    {events.error ? <EmptyState title="Unable to load events" description={eventErrorText(events.error)} action={<button className="desk-button" type="button" onClick={() => events.refetch()}>Retry</button>} /> : null}
    {events.data && !events.data.results.length ? <EmptyState title="No events yet" description="Create the first draft event above." /> : null}
    {events.data?.results.length ? <div className="overflow-x-auto rounded-xl border border-line">
      <table className="w-full text-left text-sm"><caption className="sr-only">Events in chronological order</caption>
        <thead className="bg-surface"><tr><th className="eyebrow p-3">Event</th><th className="eyebrow p-3">Status</th><th className="eyebrow p-3">Capacity</th><th className="eyebrow p-3">Registrations</th></tr></thead>
        <tbody>{events.data.results.map((item) => <tr key={item.id} className="border-t border-line">
          <td className="p-3"><button className="desk-button-ghost h-auto justify-start px-0 text-left" type="button" onClick={() => setSelectedId(item.id)}>{item.title}</button><span className="mt-1 block font-mono text-xs text-muted">{dateRange(item)}{item.location ? ` · ${item.location}` : ""}</span></td>
          <td className="p-3"><StatusBadge status={item.status} /></td>
          <td className="p-3 font-mono">{item.capacity === 0 ? "Unlimited" : item.capacity}</td>
          <td className="p-3 font-mono">{item.registration_counts.registered + item.registration_counts.attended} confirmed · {item.registration_counts.pending_approval} pending</td>
        </tr>)}</tbody>
      </table>
    </div> : null}
    {events.data ? <div className="mt-3 flex items-center justify-between gap-3 text-sm">
      <button className="desk-button" type="button" disabled={!events.data.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</button>
      <span className="font-mono text-muted">Page {page}{" - "}{events.data.count} total</span>
      <button className="desk-button" type="button" disabled={!events.data.next} onClick={() => setPage((current) => current + 1)}>Next</button>
    </div> : null}
    {selectedId !== null ? <EventDrawer key={selectedId} eventId={selectedId} makerspaceId={makerspaceId} onClose={() => setSelectedId(null)} /> : null}
  </Panel>;
}
