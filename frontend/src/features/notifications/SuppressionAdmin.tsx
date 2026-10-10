import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import type { Page } from "./PersonalInbox";

type Suppression = { id: number; address_hash: string; reason: string; created_at: string };

export function SuppressionAdmin({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const [address, setAddress] = useState("");
  const [reason, setReason] = useState("bounce");
  const [page, setPage] = useState(1);
  const key = ["notification-suppressions", makerspaceId];
  const path = `/integrations/makerspace/${makerspaceId}/email-suppressions`;
  const rows = useQuery({ queryKey: [...key, page], queryFn: () => staffRequest<Page<Suppression>>(`${path}?page=${page}`) });
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const add = useMutation({ mutationFn: () => staffRequest(path, { method: "POST", body: JSON.stringify({ address, reason }) }),
    onSuccess: () => { setAddress(""); refresh(); } });
  const remove = useMutation({ mutationFn: (id: number) => staffRequest(`${path}/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const error = rows.error ?? add.error ?? remove.error;
  return <section className="desk-panel p-5">
    <h2 className="title-panel">Email suppression</h2>
    <p className="mt-2 text-sm text-muted">Add addresses reported as hard bounces or spam complaints. Suppression stops all tenant mail, including queued retries. Addresses are stored as keyed hashes. Remove a suppression only after resolving the delivery problem.</p>
    <form className="my-3 flex flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
      <label className="grid gap-1 text-sm">Email address<input className="desk-input" type="email" maxLength={254} required value={address} onChange={(e) => setAddress(e.target.value)} /></label>
      <label className="grid gap-1 text-sm">Reason<select className="desk-input" value={reason} onChange={(e) => setReason(e.target.value)}><option value="bounce">Hard bounce</option><option value="complaint">Spam complaint</option></select></label>
      <button className="desk-button-secondary" disabled={add.isPending}>Suppress email</button>
    </form>
    {rows.isLoading ? <p className="text-sm text-muted">Loading suppressions...</p> : null}
    {error ? <p className="text-sm text-danger" role="alert">{error.message}</p> : null}
    <ul className="space-y-2">{rows.data?.results.map((row) => <li className="rounded-md border border-line p-3 text-sm" key={row.id}>
      <p>{row.reason} · {new Date(row.created_at).toLocaleDateString()}</p>
      <p className="break-all font-mono text-xs text-muted">{row.address_hash}</p>
      <button className="desk-button-ghost mt-2" disabled={remove.isPending} onClick={() => remove.mutate(row.id)}>Remove suppression</button>
    </li>)}</ul>
    <div className="mt-3 flex gap-3">
      <button className="desk-button-ghost" disabled={!rows.data?.previous} onClick={() => setPage(page - 1)}>Previous</button>
      <span className="text-sm">Page {page}</span>
      <button className="desk-button-ghost" disabled={!rows.data?.next} onClick={() => setPage(page + 1)}>Next</button>
    </div>
  </section>;
}
