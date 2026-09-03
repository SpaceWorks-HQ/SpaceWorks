import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { organizedEventKeys } from "./organizedEventsApi";

type SeriesInvitation = {
  id: number;
  series_id: number;
  series_title: string;
  host_name: string;
  host_slug: string;
  status: "invited" | "accepted" | "declined";
  next_occurrence_at: string | null;
};

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const inboxKey = (makerspaceId: number) => [
  "events", makerspaceId, "series-collaboration-inbox",
] as const;

export function EventSeriesCollaborationInbox({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const inbox = useQuery({
    queryKey: inboxKey(makerspaceId),
    queryFn: () => staffRequest<SeriesInvitation[]>(
      `/admin/makerspaces/${makerspaceId}/event-series-collaborations/`,
    ),
  });
  const respond = useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      staffRequest(`/admin/event-series-collaborations/${id}/respond/`, {
        method: "POST", body: JSON.stringify({ accept }),
      }),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: inboxKey(makerspaceId) }),
      client.invalidateQueries({ queryKey: organizedEventKeys.all }),
      client.invalidateQueries({ queryKey: ["member"] }),
    ]),
  });
  const rows = inbox.data ?? [];
  if (!rows.length) return null;

  return <section className="mb-5 rounded-xl border border-line bg-bg p-4" aria-labelledby="series-collaboration-inbox-title">
    <h3 id="series-collaboration-inbox-title" className="mb-1 font-semibold text-ink">Recurring-series invitations</h3>
    <p className="mb-3 text-sm text-muted">Accept once to make every current and future occurrence available to your members.</p>
    <ul className="space-y-3 text-sm">{rows.map((row) => <li key={row.id} className="flex flex-wrap items-center justify-between gap-2">
      <span><span className="font-medium text-ink">{row.series_title}</span><span className="block text-muted">Hosted by {row.host_name}{row.next_occurrence_at ? ` · Next ${new Date(row.next_occurrence_at).toLocaleString()}` : ""}</span></span>
      {row.status === "invited" ? <span className="flex gap-2"><button type="button" className={`desk-button-primary ${FOCUS}`} disabled={respond.isPending} onClick={() => respond.mutate({ id: row.id, accept: true })}>Accept</button><button type="button" className={`desk-button ${FOCUS}`} disabled={respond.isPending} onClick={() => respond.mutate({ id: row.id, accept: false })}>Decline</button></span> : <span className="text-muted">{row.status}</span>}
    </li>)}</ul>
    {respond.error ? <p className="mt-2 text-sm text-danger" role="alert">Could not respond to the series invitation.</p> : null}
  </section>;
}
