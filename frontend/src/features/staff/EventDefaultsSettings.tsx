import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";

type Audience = "members" | "accounts" | "invite";
type Settings = { event_default_registration_audience: Audience };

export function EventDefaultsSettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const path = `/admin/makerspaces/${makerspaceId}`;
  const key = ["makerspace-settings", makerspaceId];
  const query = useQuery({ queryKey: key, queryFn: () => staffRequest<Settings>(path) });
  const [draft, setDraft] = useState<Audience | null>(null);
  const save = useMutation({
    mutationFn: () => staffRequest<Settings>(path, { method: "PATCH", body: JSON.stringify({ event_default_registration_audience: draft }) }),
    onSuccess: (data) => {
      client.setQueryData(key, data); setDraft(null);
      void client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      void client.invalidateQueries({ queryKey: ["events", makerspaceId] });
    },
  });
  return <form className="grid gap-3 rounded-md border border-line p-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <h3 className="title-section">Event defaults</h3>
    <p className="text-sm text-muted">New events and recurring series start with this audience. Existing events keep their audience. Ticket currency uses the default in Location &amp; hours.</p>
    <label className="grid gap-1 text-sm">Default registration audience
      <select className="desk-input" value={draft ?? query.data?.event_default_registration_audience ?? "members"} disabled={!query.data || save.isPending} onChange={(event) => { setDraft(event.target.value as Audience); save.reset(); }}>
        <option value="members">Members</option><option value="accounts">Authenticated accounts</option><option value="invite">Invited accounts</option>
      </select>
    </label>
    {query.error || save.error ? <p role="alert" className="text-danger">{(save.error ?? query.error)?.message}</p> : null}
    <button className="desk-button-primary w-fit" disabled={!draft || save.isPending}>Save event defaults</button>
    {save.isSuccess ? <p role="status">Event defaults saved.</p> : null}
  </form>;
}
