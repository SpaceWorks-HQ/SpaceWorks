import { useEffect, useState, type FormEvent } from "react";

import { ConfirmDialog, DetailDrawer, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import {
  useCancelEvent, useCompleteEvent, useCreateEvent, useEvent, useEventInvalidation,
  useEventRegistrations, useEvents, useMarkEventAttended, usePublishEvent, useUpdateEvent,
  type EventPayload, type StaffEvent,
} from "./eventsApi";
import { CollaborationInbox } from "./CollaborationInbox";
import EventCheckInScanner from "./EventCheckInScanner";
import { EventCollaborators } from "./EventCollaborators";
import { EventRegisterMember } from "./EventRegisterMember";
import { ImageUploader } from "./ImageUploader";
import { Panel } from "./panels/shared";
import { PaymentReconcileActions } from "./PaymentReconcileActions";

type FormValues = Omit<EventPayload, "starts_at" | "ends_at"> & { starts_at: string; ends_at: string };
type Action = "publish" | "cancel" | "complete";

const emptyForm: FormValues = {
  title: "", description: "", starts_at: "", ends_at: "", location: "", capacity: 0, payment_amount: "0.00", is_public: false,
};

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function valuesFor(event: StaffEvent): FormValues {
  return {
    title: event.title,
    description: event.description,
    starts_at: localDate(event.starts_at),
    ends_at: localDate(event.ends_at),
    location: event.location,
    capacity: event.capacity,
    payment_amount: event.payment_amount,
    is_public: event.is_public,
  };
}

function payloadFor(values: FormValues): EventPayload {
  return { ...values, title: values.title.trim(), description: values.description.trim(), location: values.location.trim(),
    starts_at: new Date(values.starts_at).toISOString(), ends_at: new Date(values.ends_at).toISOString() };
}

function dateRange(event: StaffEvent) {
  const start = new Date(event.starts_at).toLocaleString();
  const end = new Date(event.ends_at).toLocaleString();
  return `${start} – ${end}`;
}

function errorText(error: unknown) {
  if (!(error instanceof Error)) return "Something went wrong.";
  if (error instanceof StructuredApiError && error.code) return `${error.message} (${error.code})`;
  return error.message;
}

function EventFields({ values, setValues, disabled = false }: {
  values: FormValues; setValues: (values: FormValues) => void; disabled?: boolean;
}) {
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => setValues({ ...values, [key]: value });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Title
        <input className="desk-input" value={values.title} onChange={(e) => set("title", e.target.value)} required disabled={disabled} maxLength={200} />
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink">Starts
        <input className="desk-input" type="datetime-local" value={values.starts_at} onChange={(e) => set("starts_at", e.target.value)} required disabled={disabled} />
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink">Ends
        <input className="desk-input" type="datetime-local" value={values.ends_at} onChange={(e) => set("ends_at", e.target.value)} required disabled={disabled} />
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink">Location
        <input className="desk-input" value={values.location} onChange={(e) => set("location", e.target.value)} disabled={disabled} maxLength={255} />
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink">Capacity
        <input className="desk-input" type="number" min="0" value={values.capacity} onChange={(e) => set("capacity", Number(e.target.value))} disabled={disabled} />
        <span className="text-xs font-normal text-muted">Use 0 for Unlimited.</span>
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink">Registration price
        <input className="desk-input" type="number" min="0" step="0.01" value={values.payment_amount} onChange={(e) => set("payment_amount", e.target.value)} disabled={disabled} />
        <span className="text-xs font-normal text-muted">Use 0 for no charge.</span>
      </label>
      <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Description
        <textarea className="desk-input min-h-24" value={values.description} onChange={(e) => set("description", e.target.value)} disabled={disabled} />
      </label>
      <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2">
        <input type="checkbox" checked={values.is_public} onChange={(e) => set("is_public", e.target.checked)} disabled={disabled} />
        Show this event on the public Events page
      </label>
    </div>
  );
}

export function EventsPanel({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const events = useEvents(makerspaceId, page);
  const create = useCreateEvent(makerspaceId);
  const [values, setValues] = useState(emptyForm);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(payloadFor(values), { onSuccess: (created) => { setValues(emptyForm); setSelectedId(created.id); } });
  }

  const apiError = events.error instanceof StructuredApiError ? events.error : null;
  if (apiError?.status === 403) return <Panel title="Events"><EmptyState title="Permission required" description="Only Space Managers can manage events." /></Panel>;
  if (apiError?.status === 400) return <Panel title="Events"><EmptyState title="Events module unavailable" description={apiError.message} /></Panel>;

  return (
    <Panel title="Events">
      <p className="mb-4 text-sm text-muted">Create events, publish registrations, and record attendance.</p>
      <CollaborationInbox makerspaceId={makerspaceId} />
      <form className="mb-5 rounded-xl border border-line bg-bg p-4" onSubmit={submit}>
        <h3 className="mb-3 font-semibold text-ink">Create draft event</h3>
        <EventFields values={values} setValues={setValues} />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button className="desk-button-primary" type="submit" disabled={create.isPending}>{create.isPending ? "Creating..." : "Create event"}</button>
          {create.error ? <p className="text-sm text-danger" role="alert">{errorText(create.error)}</p> : null}
        </div>
      </form>
      {events.isLoading ? <div className="grid gap-2" aria-label="Loading events">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div> : null}
      {events.error ? <EmptyState title="Unable to load events" description={errorText(events.error)} action={
        <button className="desk-button" type="button" onClick={() => events.refetch()}>Retry</button>} /> : null}
      {events.data && !events.data.results.length ? <EmptyState title="No events yet" description="Create the first draft event above." /> : null}
      {events.data?.results.length ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-left text-sm"><caption className="sr-only">Events in chronological order</caption>
            <thead className="bg-surface text-xs text-muted"><tr><th className="p-3">Event</th><th className="p-3">Status</th><th className="p-3">Capacity</th><th className="p-3">Registrations</th></tr></thead>
            <tbody>{events.data.results.map((item) => <tr key={item.id} className="border-t border-line">
              <td className="p-3"><button className="text-left font-semibold text-ink hover:underline" type="button" onClick={() => setSelectedId(item.id)}>{item.title}</button><span className="mt-1 block text-xs text-muted">{dateRange(item)}{item.location ? ` · ${item.location}` : ""}</span></td>
              <td className="p-3"><StatusBadge status={item.status} /></td><td className="p-3">{item.capacity === 0 ? "Unlimited" : item.capacity}</td>
              <td className="p-3">{item.registration_counts.registered + item.registration_counts.attended}</td>
            </tr>)}</tbody>
          </table>
        </div>
      ) : null}
      {events.data ? <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <button className="desk-button" type="button" disabled={!events.data.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>Previous</button>
        <span className="text-muted">Page {page}{" - "}{events.data.count} total</span>
        <button className="desk-button" type="button" disabled={!events.data.next} onClick={() => setPage((current) => current + 1)}>Next</button>
      </div> : null}
      {selectedId !== null ? <EventDrawer key={selectedId} eventId={selectedId} makerspaceId={makerspaceId} onClose={() => setSelectedId(null)} /> : null}
    </Panel>
  );
}

function EventDrawer({ eventId, makerspaceId, onClose }: { eventId: number; makerspaceId: number; onClose: () => void }) {
  const eventQuery = useEvent(eventId);
  const event = eventQuery.data;
  const [values, setValues] = useState(emptyForm);
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [scanning, setScanning] = useState(false);
  const registrations = useEventRegistrations(eventId, page);
  const update = useUpdateEvent(makerspaceId, eventId);
  const publish = usePublishEvent(makerspaceId, eventId);
  const cancel = useCancelEvent(makerspaceId, eventId);
  const complete = useCompleteEvent(makerspaceId, eventId);
  const attended = useMarkEventAttended(makerspaceId, eventId);
  const invalidateEvent = useEventInvalidation(makerspaceId, eventId);
  useEffect(() => { if (event) setValues(valuesFor(event)); }, [event?.updated_at]);
  const lifecycle = confirm === "publish" ? publish : confirm === "cancel" ? cancel : complete;
  const readOnly = event?.status === "cancelled" || event?.status === "completed";
  const actionError = update.error || publish.error || cancel.error || complete.error || attended.error;

  return <>
    <DetailDrawer open title={event?.title ?? "Event details"} onClose={onClose}>
      {eventQuery.isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {eventQuery.error ? <EmptyState title="Unable to load event" description={errorText(eventQuery.error)} /> : null}
      {event ? <div className="grid gap-5">
        <div className="flex flex-wrap items-center gap-2"><StatusBadge status={event.status} /><span className="text-sm text-muted">{event.capacity === 0 ? "Unlimited capacity" : `${event.capacity} places`}</span></div>
        <ImageUploader endpoint={`/admin/events/${eventId}/image`} currentUrl={event.image_url} label="Event photo (shown publicly)" shape="wide" disabled={readOnly} onChanged={invalidateEvent} />
        <form onSubmit={(e) => { e.preventDefault(); update.mutate(payloadFor(values)); }}>
          <EventFields values={values} setValues={setValues} disabled={readOnly} />
          {!readOnly ? <button className="desk-button-primary mt-3" type="submit" disabled={update.isPending}>{update.isPending ? "Saving..." : "Save changes"}</button> : <p className="mt-3 text-sm text-muted">Terminal events are read-only.</p>}
        </form>
        <div className="flex flex-wrap gap-2">
          {event.status === "draft" ? <button className="desk-button" type="button" onClick={() => setConfirm("publish")}>Publish</button> : null}
          {event.status === "published" ? <><button className="desk-button" type="button" onClick={() => setConfirm("complete")}>Complete</button><button className="desk-button text-danger" type="button" onClick={() => setConfirm("cancel")}>Cancel event</button></> : null}
        </div>
        {actionError ? <p className="text-sm text-danger" role="alert">{errorText(actionError)}</p> : null}
        <section aria-labelledby="registrations-title"><h3 id="registrations-title" className="mb-2 font-semibold text-ink">Registrations ({registrations.data?.count ?? event.registration_counts.registered + event.registration_counts.waitlisted + event.registration_counts.cancelled + event.registration_counts.attended})</h3>
          {registrations.isLoading ? <Skeleton className="h-32 w-full" /> : null}
          {registrations.error ? <p className="text-sm text-danger">{errorText(registrations.error)}</p> : null}
          {registrations.data && !registrations.data.results.length ? <p className="text-sm text-muted">No registrations yet.</p> : null}
          <EventRegisterMember makerspaceId={makerspaceId} eventId={eventId} customForm={event.custom_form} disabled={event.status !== "published"} />
          {/* Same condition as the per-row "Mark attended" button: attendance is only
              meaningful once an event is published, and staff still check people in after
              it completes. Unmounted when closed so the camera is released. */}
          {event.status === "published" || event.status === "completed" ? (
            scanning
              ? <EventCheckInScanner makerspaceId={makerspaceId} eventId={eventId} onClose={() => setScanning(false)} />
              : <button className="desk-button mt-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" type="button" onClick={() => setScanning(true)}>Scan check-in</button>
          ) : null}
          {registrations.data?.results.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Event registration contact details</caption><thead className="text-xs text-muted"><tr><th className="p-2">Name</th><th className="p-2">Contact</th><th className="p-2">Status</th><th className="p-2">Action</th></tr></thead><tbody>
            {registrations.data.results.map((row) => <tr key={row.id} className="border-t border-line"><td className="p-2">{row.name}<PaymentReconcileActions makerspaceId={makerspaceId} payment={row.payment} invalidateKeys={[["event", eventId, "registrations"], ["event", eventId], ["events", makerspaceId]]} /></td><td className="p-2"><a className="block hover:underline" href={`mailto:${row.email}`}>{row.email}</a><a className="block text-muted hover:underline" href={`tel:${row.phone}`}>{row.phone}</a></td><td className="p-2"><StatusBadge status={row.status} /></td><td className="p-2">{row.status === "registered" && (event.status === "published" || event.status === "completed") ? <button className="desk-button" type="button" disabled={attended.isPending} onClick={() => attended.mutate(row.id)}>Mark attended</button> : "—"}</td></tr>)}
          </tbody></table></div> : null}
          <div className="mt-3 flex items-center justify-between gap-2"><span className="text-xs text-muted">Page {page}</span><div className="flex gap-2"><button className="desk-button" type="button" disabled={!registrations.data?.previous} onClick={() => setPage((p) => Math.max(1, p - 1))}>Previous</button><button className="desk-button" type="button" disabled={!registrations.data?.next} onClick={() => setPage((p) => p + 1)}>Next</button></div></div>
        </section>
        <EventCollaborators makerspaceId={makerspaceId} eventId={eventId} />
      </div> : null}
    </DetailDrawer>
    <ConfirmDialog open={confirm !== null} title={`${confirm ? confirm[0].toUpperCase() + confirm.slice(1) : "Change"} event`} message={`Are you sure you want to ${confirm ?? "change"} this event?`} confirmLabel={confirm ? confirm[0].toUpperCase() + confirm.slice(1) : "Confirm"} tone={confirm === "cancel" ? "danger" : "default"} pending={lifecycle.isPending} onCancel={() => setConfirm(null)} onConfirm={() => lifecycle.mutate(undefined, { onSuccess: () => setConfirm(null), onError: () => setConfirm(null) })} />
  </>;
}
