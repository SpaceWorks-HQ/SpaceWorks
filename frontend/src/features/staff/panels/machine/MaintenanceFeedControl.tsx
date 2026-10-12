import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { staffRequest } from "../../../../lib/api";

export function MaintenanceFeedControl({ makerspaceId }: { makerspaceId: number }) {
  const [url, setUrl] = useState("");
  const feed = useMutation({ mutationFn: (method: "POST" | "DELETE") => staffRequest<{ feed_url?: string }>(`/admin/makerspaces/${makerspaceId}/maintenance/feed`, { method, ...(method === "POST" ? { body: JSON.stringify({}) } : {}) }), onSuccess: result => setUrl(result?.feed_url ?? "") });
  return <section className="grid gap-2 rounded border border-line p-3">
    <h3 className="title-section">Maintenance calendar</h3>
    <p className="text-sm text-muted">This private URL shows machines you can access. Keep it private; rotating invalidates the old URL. Usage-only schedules have no calendar date.</p>
    <div className="flex gap-2"><button className="desk-button" type="button" disabled={feed.isPending} onClick={() => feed.mutate("POST")}>Create or rotate calendar link</button><button className="desk-button-ghost" type="button" disabled={feed.isPending} onClick={() => feed.mutate("DELETE")}>Revoke calendar link</button></div>
    {url ? <input className="desk-input" aria-label="Private maintenance calendar URL" readOnly value={url} onFocus={event => event.target.select()} /> : null}
    {feed.error ? <p role="alert" className="text-sm text-danger">{feed.error.message}</p> : null}
  </section>;
}
