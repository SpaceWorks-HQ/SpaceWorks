import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { memberRequest, staffRequest } from "../../lib/api";

export type InboxRow = {
  id: number; feature: string; event: string; title: string; summary: string; link: string;
  read_at: string | null; created_at: string;
};
export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
import { inboxUnreadKey, personalRecipientKey } from "./personalQueryKeys";
export { inboxUnreadKey } from "./personalQueryKeys";

export function isInboxLink(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !/[\\\x00-\x1f\x7f]/.test(value);
}

export function PersonalInbox({ makerspaceId, member = false }: { makerspaceId: number; member?: boolean }) {
  const client = useQueryClient();
  const send = member ? memberRequest : staffRequest;
  const mode = member ? "member" : "staff";
  const recipient = personalRecipientKey();
  const [unread, setUnread] = useState(false);
  const [page, setPage] = useState(1);
  const [feature, setFeature] = useState("");
  const path = `/notifications/inbox/${makerspaceId}`;
  const params = new URLSearchParams({ page: String(page), unread: String(unread) });
  if (feature) params.set("feature", feature);
  const rows = useQuery({ queryKey: ["notifications-inbox", makerspaceId, mode, recipient, page, unread, feature],
    queryFn: () => send<Page<InboxRow>>(`${path}?${params}`), refetchInterval: 60_000 });
  const count = useQuery({ queryKey: inboxUnreadKey(makerspaceId, mode),
    queryFn: () => send<{ count: number }>(`${path}/unread-count`), refetchInterval: 60_000 });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["notifications-inbox", makerspaceId, mode, recipient] });
    client.invalidateQueries({ queryKey: inboxUnreadKey(makerspaceId, mode) });
  };
  const read = useMutation({ mutationFn: (id: number) => send(`${path}/${id}/read`, { method: "POST" }), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => send(`${path}/read-all`, { method: "POST" }), onSuccess: refresh });
  const error = rows.error ?? count.error ?? read.error ?? readAll.error;
  return <section className="desk-panel p-5" aria-label="Personal notifications">
    <h2 className="title-panel">Your inbox <span className="text-sm text-muted" aria-live="polite">({count.data?.count ?? 0} unread)</span></h2>
    <div className="my-3 flex flex-wrap items-center gap-3">
      <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={unread}
        onChange={(event) => { setUnread(event.target.checked); setPage(1); }} />Unread only</label>
      <label className="grid gap-1 text-sm">Family<select className="desk-input" value={feature}
        onChange={(event) => { setFeature(event.target.value); setPage(1); }}>
        <option value="">All families</option>
        {["hardware_requests", "printing", "events", "bookings", "maintenance", "members", "payments", "stock", "certifications", "devices", "api_access"].map((key) =>
          <option key={key} value={key}>{key.replace(/_/g, " ")}</option>)}
      </select></label>
      <button className="desk-button-success" disabled={readAll.isPending || !count.data?.count}
        onClick={() => readAll.mutate()}>Mark all read</button>
    </div>
    {rows.isLoading ? <p className="text-sm text-muted">Loading your inbox...</p> : null}
    {error ? <p className="text-sm text-danger" role="alert">{error.message}</p> : null}
    {rows.data?.results.length === 0 ? <p className="text-sm text-muted">No notifications.</p> : null}
    <ul className="space-y-3">{rows.data?.results.map((row) => <li key={row.id}
      className={`rounded-md border p-3 ${row.read_at ? "border-line" : "border-accent"}`}>
      <p className="text-xs text-muted">{row.feature.replace(/_/g, " ")} · {new Date(row.created_at).toLocaleString()}</p>
      <h3 className="font-semibold text-ink">{row.title}</h3>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted">{row.summary}</p>
      <div className="mt-2 flex gap-3">{isInboxLink(row.link) ?
        <a className="desk-button-secondary" href={row.link}>Open</a> : null}
      {!row.read_at ? <button className="desk-button-success" disabled={read.isPending} onClick={() => read.mutate(row.id)}>Mark read</button> : null}</div>
    </li>)}</ul>
    <div className="mt-4 flex items-center gap-3">
      <button className="desk-button-ghost" disabled={!rows.data?.previous} onClick={() => setPage(page - 1)}>Previous</button>
      <span className="text-sm text-muted">Page {page}</span>
      <button className="desk-button-ghost" disabled={!rows.data?.next} onClick={() => setPage(page + 1)}>Next</button>
    </div>
  </section>;
}
