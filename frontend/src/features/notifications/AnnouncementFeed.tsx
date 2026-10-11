import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { memberRequest } from "../../lib/api";
import { personalRecipientKey } from "./personalQueryKeys";

type Page = { next: string | null; previous: string | null; results: { id: number; title: string; summary: string; created_at: string }[] };

export function AnnouncementFeed({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const feed = useQuery({ queryKey: ["notifications-inbox", makerspaceId, "member", personalRecipientKey(), "announcements", page],
    queryFn: () => memberRequest<Page>(`/notifications/announcements/${makerspaceId}?page=${page}`), refetchInterval: 60_000 });
  return <section className="desk-panel p-5" aria-label="Member announcements">
    <h2 className="title-panel">Announcements</h2>
    {feed.isLoading ? <p role="status">Loading announcements…</p> : null}
    {feed.error ? <p role="alert" className="text-danger">{feed.error.message}</p> : null}
    {feed.data?.results.length === 0 ? <p className="text-sm text-muted">No announcements.</p> : null}
    <ul className="mt-3 grid gap-3">{feed.data?.results.map((row) => <li key={row.id} className="rounded-lg border border-line p-3"><h3 className="font-semibold">{row.title}</h3><p className="mt-1 whitespace-pre-wrap text-sm">{row.summary}</p></li>)}</ul>
    {feed.data?.next || feed.data?.previous ? <div className="mt-3 flex gap-2"><button className="desk-button-secondary" disabled={!feed.data.previous || feed.isFetching} onClick={() => setPage(page - 1)}>Previous</button><button className="desk-button-secondary" disabled={!feed.data.next || feed.isFetching} onClick={() => setPage(page + 1)}>Next</button></div> : null}
  </section>;
}
