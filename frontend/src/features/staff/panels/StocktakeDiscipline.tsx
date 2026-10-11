import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";

type Policy = { blind_default: boolean; variance_threshold: number | null };
type Schedule = { id: number; name: string; next_due: string; interval_days: number; blind: boolean; is_active: boolean };

export function StocktakeDiscipline({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const base = `/admin/makerspace/${makerspaceId}`;
  const policy = useQuery({ queryKey: ["stocktake-policy", makerspaceId], queryFn: () => staffRequest<Policy>(`${base}/stocktake-policy`) });
  const schedules = usePaginatedQuery<Schedule>({ key: ["stocktake-schedules", makerspaceId], path: `${base}/stocktake-schedules`, resetKey: String(makerspaceId) });
  const [draft, setDraft] = useState<Policy>({ blind_default: false, variance_threshold: null });
  const [name, setName] = useState("Cycle count");
  const [days, setDays] = useState(30);
  const [due, setDue] = useState("");
  useEffect(() => { if (policy.data) setDraft(policy.data); }, [policy.data]);
  const save = useMutation({ mutationFn: () => staffRequest(`${base}/stocktake-policy`, { method: "PUT", body: JSON.stringify(draft) }), onSuccess: () => client.invalidateQueries({ queryKey: ["stocktake-policy", makerspaceId] }) });
  const create = useMutation({ mutationFn: () => staffRequest(`${base}/stocktake-schedules`, { method: "POST", body: JSON.stringify({ name, interval_days: days, next_due: due, blind: draft.blind_default }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["stocktake-schedules", makerspaceId] }) });
  const toggle = useMutation({ mutationFn: (row: Schedule) => staffRequest(`${base}/stocktake-schedules/${row.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !row.is_active }) }), onSuccess: () => client.invalidateQueries({ queryKey: ["stocktake-schedules", makerspaceId] }) });
  return <section className="my-3 grid gap-3 rounded border border-line p-3">
    <h3 className="title-section">Stocktake policy and schedule</h3>
    <form className="grid gap-2" onSubmit={event => { event.preventDefault(); save.mutate(); }}>
      <label className="flex gap-2 text-sm"><input type="checkbox" checked={draft.blind_default} onChange={event => setDraft({ ...draft, blind_default: event.target.checked })} />Blind counts by default</label>
      <label className="grid gap-1 text-sm">Variance units allowed without approval (blank requires every session to be approved)<input className="desk-input" type="number" min={0} value={draft.variance_threshold ?? ""} onChange={event => setDraft({ ...draft, variance_threshold: event.target.value === "" ? null : Number(event.target.value) })} /></label>
      <button className="desk-button" disabled={save.isPending || !policy.data}>Save policy</button>
    </form>
    <form className="grid gap-2" onSubmit={event => { event.preventDefault(); create.mutate(); }}>
      <label className="grid gap-1 text-sm">Count name<input required className="desk-input" value={name} onChange={event => setName(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Every days<input required type="number" min={1} className="desk-input" value={days} onChange={event => setDays(Number(event.target.value))} /></label>
      <label className="grid gap-1 text-sm">First count due<input required type="date" className="desk-input" value={due} onChange={event => setDue(event.target.value)} /></label>
      <button className="desk-button" disabled={create.isPending}>Schedule count</button>
    </form>
    {schedules.data?.results.map(row => <div key={row.id} className="flex flex-wrap gap-2 text-sm"><span>{row.name} · {row.next_due} · every {row.interval_days} days</span><button type="button" className="desk-button-ghost" disabled={toggle.isPending} onClick={() => toggle.mutate(row)}>{row.is_active ? "Pause schedule" : "Enable schedule"}</button></div>)}
    <Pagination page={schedules.page} totalPages={schedules.totalPages} count={schedules.count} pageSize={schedules.pageSize} onChange={schedules.setPage} />
    {[policy.error, schedules.error, save.error, create.error, toggle.error].map((error, index) => error ? <p role="alert" key={index} className="text-sm text-danger">{error.message}</p> : null)}
  </section>;
}
