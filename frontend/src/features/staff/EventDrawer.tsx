import { useEffect, useState } from "react";

import { ConfirmDialog, DetailDrawer, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { EventCollaborators } from "./EventCollaborators";
import { EventFields, emptyEventForm, payloadFor, valuesFor } from "./EventFormFields";
import { EventFeedbackPanel } from "./EventFeedbackPanel";
import { EventRegistrationRoster } from "./EventRegistrationRoster";
import { ImageUploader } from "./ImageUploader";
import {
  useCancelEvent,
  useCompleteEvent,
  useEvent,
  useEventInvalidation,
  usePublishEvent,
  useUpdateEvent,
} from "./eventsApi";
import { eventErrorText } from "./eventUi";

type Action = "publish" | "cancel" | "complete";

export function EventDrawer({ eventId, makerspaceId, onClose }: {
  eventId: number;
  makerspaceId: number;
  onClose: () => void;
}) {
  const eventQuery = useEvent(eventId);
  const event = eventQuery.data;
  const [values, setValues] = useState(emptyEventForm);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const update = useUpdateEvent(makerspaceId, eventId);
  const publish = usePublishEvent(makerspaceId, eventId);
  const cancel = useCancelEvent(makerspaceId, eventId);
  const complete = useCompleteEvent(makerspaceId, eventId);
  const invalidateEvent = useEventInvalidation(makerspaceId, eventId);

  useEffect(() => { if (event) setValues(valuesFor(event)); }, [event?.updated_at]);
  const lifecycle = confirm === "publish" ? publish : confirm === "cancel" ? cancel : complete;
  const readOnly = event?.status === "cancelled" || event?.status === "completed";
  const actionError = update.error || publish.error || cancel.error || complete.error;

  return <>
    <DetailDrawer open title={event?.title ?? "Event details"} onClose={onClose}>
      {eventQuery.isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {eventQuery.error ? <EmptyState title="Unable to load event" description={eventErrorText(eventQuery.error)} /> : null}
      {event ? <div className="grid gap-5">
        <div className="flex flex-wrap items-center gap-2"><StatusBadge status={event.status} /><span className="text-sm text-muted">{event.capacity === 0 ? "Unlimited capacity" : `${event.capacity} places`} · Registration {event.registration_open ? "open" : "closed"}</span></div>
        {event.effective_registration_cutoff_at ? <p className="text-sm text-muted">Effective cutoff: <span className="font-mono">{new Date(event.effective_registration_cutoff_at).toLocaleString()}</span></p> : null}
        <ImageUploader endpoint={`/admin/events/${eventId}/image`} currentUrl={event.image_url} label="Event photo (shown publicly)" shape="wide" disabled={readOnly} onChanged={invalidateEvent} />
        <form onSubmit={(e) => { e.preventDefault(); update.mutate(payloadFor(values)); }}>
          <EventFields values={values} setValues={setValues} disabled={readOnly} approvalLocked={event.status !== "draft"} />
          {!readOnly ? <button className="desk-button-primary mt-3" type="submit" disabled={update.isPending}>{update.isPending ? "Saving..." : "Save changes"}</button> : <p className="mt-3 text-sm text-muted">Terminal events are read-only.</p>}
        </form>
        <div className="flex flex-wrap gap-2">
          {event.status === "draft" ? <button className="desk-button-primary" type="button" onClick={() => setConfirm("publish")}>Publish</button> : null}
          {event.status === "published" ? <><button className="desk-button-success" type="button" onClick={() => setConfirm("complete")}>Complete</button><button className="desk-button-danger" type="button" onClick={() => setConfirm("cancel")}>Cancel event</button></> : null}
        </div>
        {actionError ? <p className="text-sm text-danger" role="alert">{eventErrorText(actionError)}</p> : null}
        <EventRegistrationRoster event={event} makerspaceId={makerspaceId} />
        <EventFeedbackPanel eventId={eventId} makerspaceId={makerspaceId} />
        <EventCollaborators makerspaceId={makerspaceId} eventId={eventId} />
      </div> : null}
    </DetailDrawer>
    <ConfirmDialog open={confirm !== null} title={`${confirm ? confirm[0].toUpperCase() + confirm.slice(1) : "Change"} event`} message={`Are you sure you want to ${confirm ?? "change"} this event?`} confirmLabel={confirm ? confirm[0].toUpperCase() + confirm.slice(1) : "Confirm"} tone={confirm === "cancel" ? "danger" : "default"} pending={lifecycle.isPending} onCancel={() => setConfirm(null)} onConfirm={() => lifecycle.mutate(undefined, { onSuccess: () => setConfirm(null), onError: () => setConfirm(null) })} />
  </>;
}
