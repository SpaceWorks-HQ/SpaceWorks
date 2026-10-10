import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../../../lib/api";

type Policy = { cert_reminder_days: number | null; reminder_lead_days: number | null; grace_days: number | null };
export function MachineReminderPolicy({ makerspaceId, machineTypeId }: { makerspaceId: number; machineTypeId: number }) {
  const path = `/admin/makerspace/${makerspaceId}/machine-types/${machineTypeId}/policy`;
  const key = ["machine-policy", makerspaceId, machineTypeId];
  const client = useQueryClient();
  const query = useQuery({ queryKey: key, queryFn: () => staffRequest<Policy>(path) });
  const [draft, setDraft] = useState<Policy>({ cert_reminder_days: null, reminder_lead_days: null, grace_days: null });
  useEffect(() => { if (query.data) setDraft(query.data); }, [query.data]);
  const save = useMutation({ mutationFn: () => staffRequest<Policy>(path, { method: "PUT", body: JSON.stringify(draft) }), onSuccess: () => client.invalidateQueries({ queryKey: key }) });
  return <section className="rounded-xl border border-line bg-panel p-3">
    <h3 className="title-panel">Reminder policy</h3><p className="my-2 text-sm text-muted">Enable certification or maintenance reminders in makerspace features and choose notification channels. Blank uses defaults; zero disables advance reminders.</p>
    {query.isLoading ? <p role="status">Loading policy…</p> : null}
    {query.isSuccess ? <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      {([["cert_reminder_days", "Certification lead days (default 14)"], ["reminder_lead_days", "Maintenance lead days (default 7)"], ["grace_days", "Overdue grace days (default 0)"]] as const).map(([field, label]) => <label key={field} className="grid gap-1 text-sm">{label}<input className="desk-input" type="number" min={0} max={365} value={draft[field] ?? ""} onChange={(e) => setDraft({ ...draft, [field]: e.target.value === "" ? null : Number(e.target.value) })} /></label>)}
      <button className="desk-button-primary w-fit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save policy"}</button>{save.isSuccess ? <p role="status">Policy saved.</p> : null}
    </form> : null}
    {[query.error, save.error].map((error, index) => error instanceof Error ? <p className="text-sm text-danger" role="alert" key={index}>{error.message}</p> : null)}
  </section>;
}
