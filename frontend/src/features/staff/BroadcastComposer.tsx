import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";

type Choice = { id: number; name: string };
type Options = { plans: Choice[]; certifications: Choice[] };
type Result = { recipients: number; broadcast: { id: number } };

export function BroadcastComposer({ makerspaceId }: { makerspaceId: number }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [plan, setPlan] = useState("");
  const [status, setStatus] = useState("");
  const [certification, setCertification] = useState("");
  const client = useQueryClient();
  const path = `/notifications/broadcasts/${makerspaceId}`;
  const options = useQuery({ queryKey: ["broadcast-options", makerspaceId], queryFn: () => staffRequest<Options>(path) });
  const send = useMutation({ mutationFn: () => staffRequest<Result>(path, {
    method: "POST", body: JSON.stringify({ title, body,
      ...(plan ? { plan_id: Number(plan) } : {}), ...(status ? { status } : {}),
      ...(certification ? { certification_id: Number(certification) } : {}),
    }),
  }), onSuccess: async () => { setTitle(""); setBody(""); await client.invalidateQueries({ queryKey: ["notifications-inbox", makerspaceId] }); } });
  const submit = (event: FormEvent) => { event.preventDefault(); send.mutate(); };
  return <form onSubmit={submit} className="desk-panel mb-4 grid gap-3 p-5" aria-label="Member broadcast">
    <h2 className="title-panel">Send a member announcement</h2>
    <p className="text-sm text-muted">All selected conditions must match. Personal opt-outs and makerspace channel settings apply. Only active, unrestricted accounts receive announcements.</p>
    <fieldset className="grid gap-3 sm:grid-cols-3" disabled={send.isPending || options.isLoading || options.isError}>
      <label className="grid gap-1 text-sm">Plan<select className="desk-input" value={plan} onChange={(event) => setPlan(event.target.value)}><option value="">All plans</option>{options.data?.plans.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className="grid gap-1 text-sm">Plan status<select className="desk-input" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Any plan status</option><option value="active">Current term</option><option value="lapsed">Lapsed term</option></select></label>
      <label className="grid gap-1 text-sm">Certification<select className="desk-input" value={certification} onChange={(event) => setCertification(event.target.value)}><option value="">Any certification</option>{options.data?.certifications.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <label className="grid gap-1 text-sm sm:col-span-3">Title<input className="desk-input" required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      <label className="grid gap-1 text-sm sm:col-span-3">Message<textarea className="desk-input" required maxLength={12000} value={body} onChange={(event) => setBody(event.target.value)} /></label>
    </fieldset>
    {options.isLoading ? <p role="status">Loading segments…</p> : null}
    {options.error || send.error ? <p role="alert" className="text-sm text-danger">{(send.error ?? options.error)?.message}</p> : null}
    <button type="submit" className="desk-button-primary w-fit" disabled={send.isPending || options.isLoading || options.isError}>{send.isPending ? "Sending…" : "Send announcement"}</button>
    {send.data ? <p role="status" className="text-sm">Announcement queued for {send.data.recipients} eligible members. Delivery follows their channel preferences.</p> : null}
  </form>;
}
