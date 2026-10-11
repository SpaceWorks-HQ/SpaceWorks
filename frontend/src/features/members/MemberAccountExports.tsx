import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountKey, exportDownload, ownExports, requestExport } from "./memberAccountApi";

export function MemberAccountExports({ makerspaceId }: { makerspaceId: number }) {
  const [page, setPage] = useState(1);
  const client = useQueryClient();
  const rows = useQuery({ queryKey: [...accountKey(makerspaceId), "exports", page], queryFn: () => ownExports(makerspaceId, page), retry: false,
    refetchInterval: (query) => query.state.data?.results.some((job) => ["pending", "running"].includes(job.status)) ? 5000 : false });
  const create = useMutation({ mutationFn: () => requestExport(makerspaceId), onSuccess: () => { setPage(1); void client.invalidateQueries({ queryKey: [...accountKey(makerspaceId), "exports"] }); } });
  const download = useMutation({ mutationFn: (id: string) => exportDownload(makerspaceId, id) });
  return <section className="desk-panel p-5"><h2 className="title-panel">Export your data</h2>
    <p className="mt-2 text-sm text-muted">Download your profile, membership, history and payment records held by this makerspace as JSON in a ZIP. Export requests are limited to one per day. Files expire automatically.</p>
    <button className="desk-button-secondary mt-3" disabled={create.isPending} onClick={() => create.mutate()}>Request data export</button>
    {rows.isLoading ? <p role="status">Loading exports…</p> : null}
    {rows.error || create.error || download.error ? <p role="alert" className="text-danger">{(rows.error || create.error || download.error)?.message}</p> : null}
    {rows.data?.results.map((job) => <div key={job.id} className="border-t border-line py-3 mt-3"><p>Requested {new Date(job.created_at).toLocaleString()} · {job.status}</p>
      {job.status === "failed" ? <p role="alert">{job.failure_detail}</p> : null}
      {job.status === "available" && new Date(job.expires_at).getTime() > Date.now() ? <button className="desk-button mt-2" disabled={download.isPending} onClick={() => download.mutate(job.id)}>Prepare download link</button> : null}
    </div>)}
    {download.data ? <p className="mt-3"><a className="desk-button-primary" href={download.data.url} rel="noreferrer">Download ZIP</a> Link expires {new Date(download.data.expires_at).toLocaleTimeString()}.</p> : null}
    <div className="flex gap-2 mt-3"><button className="desk-button" disabled={!rows.data?.previous} onClick={() => setPage(page - 1)}>Previous exports</button><button className="desk-button" disabled={!rows.data?.next} onClick={() => setPage(page + 1)}>Next exports</button></div>
  </section>;
}
