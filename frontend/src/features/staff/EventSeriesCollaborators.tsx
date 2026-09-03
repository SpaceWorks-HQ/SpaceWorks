import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { eventSeriesKeys } from "./eventSeriesApi";
import { eventKeys } from "./eventsApi";
import { organizedEventKeys } from "./organizedEventsApi";

type Collaborator = {
  id: number; makerspace_name: string; makerspace_slug: string; status: string;
};

export function EventSeriesCollaborators({ seriesId, makerspaceId }: { seriesId: number; makerspaceId: number }) {
  const client = useQueryClient();
  const [slug, setSlug] = useState("");
  const path = `/admin/event-series/${seriesId}/collaborators/`;
  const query = useQuery({
    queryKey: eventSeriesKeys.collaborators(seriesId),
    queryFn: () => staffRequest<Collaborator[]>(path),
  });
  const invalidate = () => Promise.all([
    client.invalidateQueries({ queryKey: eventSeriesKeys.collaborators(seriesId) }),
    client.invalidateQueries({ queryKey: eventSeriesKeys.occurrences(seriesId) }),
    client.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    client.invalidateQueries({ queryKey: organizedEventKeys.all }),
    client.invalidateQueries({ queryKey: ["member"] }),
  ]);
  const replace = useMutation({
    mutationFn: (slugs: string[]) => staffRequest<Collaborator[]>(path, {
      method: "PUT", body: JSON.stringify({ slugs }),
    }), onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: number) => staffRequest<void>(`/admin/event-series-collaborations/${id}/remove/`, { method: "POST" }),
    onSuccess: invalidate,
  });
  const rows = query.data ?? [];
  return <section aria-labelledby="series-collaborators-title">
    <h3 id="series-collaborators-title" className="title-section">Series partners</h3>
    <p className="mt-1 text-sm text-muted">One accepted invitation applies to every current and future occurrence.</p>
    <ul className="mt-3 space-y-2 text-sm">{rows.map((row) => <li key={row.id} className="flex items-center justify-between gap-2"><span>{row.makerspace_name} ({row.makerspace_slug}) · {row.status}</span><button className="desk-button text-danger" type="button" disabled={remove.isPending} onClick={() => remove.mutate(row.id)}>Remove</button></li>)}</ul>
    <div className="mt-3 flex flex-wrap items-end gap-2"><label className="grid gap-1 text-sm font-semibold text-ink">Makerspace slug<input className="desk-input" value={slug} onChange={(e) => setSlug(e.target.value)} /></label><button className="desk-button" type="button" disabled={!slug.trim() || replace.isPending} onClick={() => replace.mutate(Array.from(new Set([...rows.map((row) => row.makerspace_slug), slug.trim().toLowerCase()])), { onSuccess: () => setSlug("") })}>Invite</button></div>
    {query.error || replace.error || remove.error ? <p className="mt-2 text-sm text-danger" role="alert">Could not update series partners.</p> : null}
  </section>;
}
