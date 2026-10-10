import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { memberRequest } from "../../lib/api";

type Certification = { id: number; name: string; machine_type_name: string; type_active: boolean; is_live: boolean; granted_at: string; expires_at: string | null; revoked_at: string | null };
type Page = { count: number; next: string | null; previous: string | null; results: Certification[] };
export function MemberCertifications({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ["member", makerspaceId, "certifications", page], queryFn: () => memberRequest<Page>(`/member/makerspaces/${makerspaceId}/certifications?page=${page}`) });
  return <section className="desk-panel p-5" aria-label="Your certifications">
    <h2 className="title-panel">Your certifications</h2>
    {query.isLoading ? <p role="status">Loading certifications…</p> : null}
    {query.error instanceof Error ? <p role="alert" className="text-danger">{query.error.message}</p> : null}
    {query.isSuccess && !query.data.count ? <p className="mt-2 text-sm text-muted">No training records yet. Ask staff about machine induction.</p> : null}
    <ul className="mt-3 grid gap-3">{query.data?.results.map((row) => <li key={row.id} className="rounded-lg border border-line p-3 text-sm">
      <strong>{row.name}</strong><p className="text-muted">{row.machine_type_name} · {!row.type_active ? "Type inactive" : row.revoked_at ? "Revoked" : row.is_live ? "Valid" : "Expired"}</p>
      <p>{row.expires_at ? `Expiry: ${new Date(row.expires_at).toLocaleDateString()}` : "Does not expire"}</p>
      {row.type_active && !row.revoked_at && row.expires_at && (!row.is_live || new Date(row.expires_at).getTime() - Date.now() < 14 * 86400000) ? <p className="mt-1 text-warn">Ask staff to reassess and renew your training.</p> : null}
    </li>)}</ul>
    {query.data && query.data.count > 24 ? <div className="mt-3 flex gap-2"><button className="desk-button-ghost" disabled={page === 1 || query.isFetching} onClick={() => setPage(page - 1)}>Previous</button><button className="desk-button-ghost" disabled={!query.data.next || query.isFetching} onClick={() => setPage(page + 1)}>Next</button></div> : null}
  </section>;
}
