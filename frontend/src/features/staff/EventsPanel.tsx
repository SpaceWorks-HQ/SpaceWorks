import { useState, type FormEvent } from "react";

import { EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { CollaborationInbox } from "./CollaborationInbox";
import { EventDrawer } from "./EventDrawer";
import { EventSeriesDrawer } from "./EventSeriesDrawer";
import { EventSeriesCollaborationInbox } from "./EventSeriesCollaborationInbox";
import { EventSeriesFields, emptySeriesForm, seriesPayload } from "./EventSeriesForm";
import { eventErrorText } from "./eventUi";
import {
  EventFields,
  emptyEventForm,
  payloadFor,
  type EventFormValues,
} from "./EventFormFields";
import { useCreateEvent, useEvents, type StaffEvent } from "./eventsApi";
import { useCreateEventSeries, useEventSeriesList } from "./eventSeriesApi";
import { Panel } from "./panels/shared";

export { EventDrawer };

function dateRange(event: StaffEvent) {
  return `${new Date(event.starts_at).toLocaleString()} – ${new Date(event.ends_at).toLocaleString()}`;
}

export function EventsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const events = useEvents(makerspaceId, page);
  const create = useCreateEvent(makerspaceId);
  const series = useEventSeriesList(makerspaceId);
  const createSeries = useCreateEventSeries(makerspaceId);
  const [values, setValues] = useState<EventFormValues>(emptyEventForm);
  const [seriesValues, setSeriesValues] = useState(emptySeriesForm);
  const [creationMode, setCreationMode] = useState<"single" | "series">("single");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(payloadFor(values), {
      onSuccess: (created) => {
        setValues(emptyEventForm);
        setSelectedId(created.id);
      },
    });
  }
  function submitSeries(event: FormEvent) {
    event.preventDefault();
    createSeries.mutate(seriesPayload(seriesValues), {
      onSuccess: (created) => {
        setSeriesValues(emptySeriesForm);
        setSelectedSeriesId(created.series.id);
      },
    });
  }

  const apiError = events.error instanceof StructuredApiError ? events.error : null;
  if (apiError?.status === 403) return <Panel title="Events"><EmptyState title="Permission required" description="Event management access is required." /></Panel>;
  if (apiError?.status === 400) return <Panel title="Events"><EmptyState title="Events module unavailable" description={apiError.message} /></Panel>;

  return <Panel title="Events">
    <p className="mb-4 text-sm text-muted">Create events, review applications, and record attendance.</p>
    <CollaborationInbox makerspaceId={makerspaceId} />
    <EventSeriesCollaborationInbox makerspaceId={makerspaceId} />
    <div className="mb-3 flex gap-2" role="group" aria-label="Event type"><button className={creationMode === "single" ? "desk-button-primary" : "desk-button"} type="button" onClick={() => setCreationMode("single")}>One-time event</button><button className={creationMode === "series" ? "desk-button-primary" : "desk-button"} type="button" onClick={() => setCreationMode("series")}>Recurring series</button></div>
    <form className="mb-5 rounded-xl border border-line bg-bg p-4" onSubmit={creationMode === "single" ? submit : submitSeries}>
      <h3 className="title-section mb-3">Create draft {creationMode === "single" ? "event" : "series"}</h3>
      {creationMode === "single" ? <EventFields values={values} setValues={setValues} /> : <EventSeriesFields values={seriesValues} setValues={setSeriesValues} />}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="desk-button-primary" type="submit" disabled={create.isPending || createSeries.isPending}>{create.isPending || createSeries.isPending ? "Creating..." : creationMode === "single" ? "Create event" : "Create series"}</button>
        {create.error || createSeries.error ? <p className="text-sm text-danger" role="alert">{eventErrorText(create.error || createSeries.error)}</p> : null}
      </div>
    </form>
    <section className="mb-5"><h3 className="title-section mb-3">Recurring series</h3>{series.isLoading ? <Skeleton className="h-20 w-full" /> : null}{series.error ? <p className="text-sm text-danger" role="alert">{eventErrorText(series.error)}</p> : null}{series.data && !series.data.results.length ? <p className="text-sm text-muted">No recurring series yet.</p> : null}<div className="grid gap-2">{series.data?.results.map((row) => <button key={row.id} className="desk-button-ghost justify-between border border-line p-3" type="button" onClick={() => setSelectedSeriesId(row.id)}><span className="text-left"><span className="font-semibold">{row.title}</span><span className="block text-xs text-muted">{row.next_occurrence_at ? `Next: ${new Date(row.next_occurrence_at).toLocaleString()}` : "No future occurrence"} · {row.future_occurrence_count} buffered</span></span><StatusBadge status={row.status} /></button>)}</div></section>
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
    {selectedSeriesId !== null ? <EventSeriesDrawer key={selectedSeriesId} seriesId={selectedSeriesId} makerspaceId={makerspaceId} onClose={() => setSelectedSeriesId(null)} onSelectOccurrence={(eventId) => { setSelectedSeriesId(null); setSelectedId(eventId); }} /> : null}
  </Panel>;
}
