import { useEffect, useState, type FormEvent } from "react";

import { ConfirmDialog, DetailDrawer, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { EventSeriesCollaborators } from "./EventSeriesCollaborators";
import { ImageUploader } from "./ImageUploader";
import { EventSeriesFields, emptySeriesForm, seriesPayload, valuesForSeries } from "./EventSeriesForm";
import {
  useEventSeries,
  useEventSeriesAction,
  useEventSeriesOccurrences,
  useUpdateEventSeries,
} from "./eventSeriesApi";
import { eventErrorText } from "./eventUi";

type Action = "publish" | "cancel" | "complete" | "extend";

export function EventSeriesDrawer({ seriesId, makerspaceId, onClose, onSelectOccurrence }: {
  seriesId: number; makerspaceId: number; onClose: () => void;
  onSelectOccurrence: (eventId: number) => void;
}) {
  const query = useEventSeries(seriesId);
  const occurrences = useEventSeriesOccurrences(seriesId);
  const update = useUpdateEventSeries(makerspaceId, seriesId);
  const [values, setValues] = useState(emptySeriesForm);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const publish = useEventSeriesAction(makerspaceId, seriesId, "publish");
  const cancel = useEventSeriesAction(makerspaceId, seriesId, "cancel");
  const complete = useEventSeriesAction(makerspaceId, seriesId, "complete");
  const extend = useEventSeriesAction(makerspaceId, seriesId, "extend");
  const action = confirm === "publish" ? publish : confirm === "cancel" ? cancel : confirm === "complete" ? complete : extend;
  useEffect(() => { if (query.data) setValues(valuesForSeries(query.data)); }, [query.data?.updated_at]);
  const terminal = query.data?.status === "cancelled" || query.data?.status === "completed";
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const payload = seriesPayload(values);
    update.mutate({ ...payload, ...(query.data?.status === "published" ? { effective_from: new Date().toISOString() } : {}) });
  };
  return <>
    <DetailDrawer open title={query.data?.title ?? "Recurring series"} onClose={onClose}>
      {query.isLoading ? <Skeleton className="h-64 w-full" /> : null}
      {query.error ? <EmptyState title="Unable to load series" description={eventErrorText(query.error)} /> : null}
      {query.data ? <div className="grid gap-5">
        <div className="flex flex-wrap items-center gap-2"><StatusBadge status={query.data.status} /><span className="text-sm text-muted">{query.data.future_occurrence_count} active occurrences · revision {query.data.revision}</span></div>
        {query.data.last_generation_error_code ? <div className="rounded-lg border border-danger bg-danger/10 p-3 text-sm text-danger" role="alert">Automatic extension needs attention ({query.data.last_generation_error_code}). Use Extend now after correcting the schedule.</div> : null}
        <ImageUploader endpoint={`/admin/event-series/${seriesId}/image`} currentUrl={query.data.image_url} label="Series photo (inherited by occurrences)" shape="wide" disabled={terminal} onChanged={() => query.refetch()} />
        <form onSubmit={submit}><h3 className="title-section mb-3">Edit future occurrences</h3><EventSeriesFields values={values} setValues={setValues} disabled={terminal} />{!terminal ? <button className="desk-button-primary mt-3" type="submit" disabled={update.isPending}>Save future occurrences</button> : null}</form>
        <div className="flex flex-wrap gap-2">{query.data.status === "draft" ? <button className="desk-button-primary" type="button" onClick={() => setConfirm("publish")}>Publish series</button> : null}{query.data.status === "published" ? <><button className="desk-button" type="button" onClick={() => setConfirm("extend")}>Extend now</button><button className="desk-button-success" type="button" onClick={() => setConfirm("complete")}>Complete series</button><button className="desk-button-danger" type="button" onClick={() => setConfirm("cancel")}>Cancel series</button></> : null}</div>
        {update.error || action.error ? <p className="text-sm text-danger" role="alert">{eventErrorText(update.error || action.error)}</p> : null}
        <section><h3 className="title-section">Occurrences</h3><p className="mt-1 text-sm text-muted">Choose one occurrence to edit or cancel only that date.</p>{occurrences.isLoading ? <Skeleton className="mt-3 h-24 w-full" /> : null}<ul className="mt-3 space-y-2">{occurrences.data?.results.map((row) => <li key={row.id}><button className="desk-button-ghost w-full justify-between" type="button" onClick={() => onSelectOccurrence(row.id)}><span>{new Date(row.starts_at).toLocaleString()}</span><StatusBadge status={row.status} /></button></li>)}</ul></section>
        <EventSeriesCollaborators seriesId={seriesId} makerspaceId={makerspaceId} />
      </div> : null}
    </DetailDrawer>
    <ConfirmDialog open={confirm !== null} title={`${confirm ?? "Change"} recurring series`} message={`This will ${confirm ?? "change"} the series and its applicable occurrences.`} confirmLabel="Confirm" tone={confirm === "cancel" ? "danger" : "default"} pending={action.isPending} onCancel={() => setConfirm(null)} onConfirm={() => action.mutate(undefined, { onSettled: () => setConfirm(null) })} />
  </>;
}
