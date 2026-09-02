import { useState } from "react";

import { Skeleton } from "../../components/ui";
import { EventCertificateActions } from "./EventCertificateActions";
import { useEventFeedbackResponses } from "./eventFeedbackApi";
import { eventErrorText } from "./eventUi";

export function EventFeedbackResponses({ eventId, makerspaceId, responseCount }: {
  eventId: number;
  makerspaceId: number;
  responseCount: number;
}) {
  const [page, setPage] = useState(1);
  const responses = useEventFeedbackResponses(eventId, page, true);
  return <div className="mt-5">
    <h4 className="title-section">Responses <span className="font-mono">({responses.data?.count ?? responseCount})</span></h4>
    {responses.isLoading ? <Skeleton className="mt-2 h-24 w-full" /> : null}
    {responses.error ? <p className="mt-2 text-sm text-danger">{eventErrorText(responses.error)}</p> : null}
    {responses.data?.results.map((response) => <article key={response.id} className="mt-2 rounded-lg border border-line p-3 text-sm">
      <p className="font-medium text-ink">{response.identity?.name ?? "Anonymous response"}</p>
      <p className="text-xs text-muted">{new Date(response.created_at).toLocaleString()}</p>
      <dl className="mt-2 grid gap-1">{response.answers.answers.map((answer) => <div key={answer.id}><dt className="eyebrow">{answer.label}</dt><dd className="whitespace-pre-wrap text-ink">{Array.isArray(answer.value) ? answer.value.join(", ") : String(answer.value)}</dd></div>)}</dl>
      {response.certificate ? <EventCertificateActions certificate={response.certificate} eventId={eventId} makerspaceId={makerspaceId} /> : null}
    </article>)}
    <div className="mt-3 flex gap-2"><button className="desk-button" type="button" disabled={!responses.data?.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><button className="desk-button" type="button" disabled={!responses.data?.next} onClick={() => setPage((value) => value + 1)}>Next</button></div>
  </div>;
}
