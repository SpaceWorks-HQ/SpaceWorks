import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import type { Page } from "./PersonalInbox";
import { SuppressionAdmin } from "./SuppressionAdmin";

type Delivery = {
  id: number; kind: "email" | "channel"; channel: string; feature: string; event: string;
  destination_id: number | null; destination_label: string; status: string; error: string;
  attempts: number; retry_generation: number; created_at: string; sent_at: string | null;
};
type Destination = { id: number; label: string; channel: string; is_active: boolean };
type TestResult = { kind: string; id: number; status: string };

export function DeliveryLogScreen({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState({ channel: "", status: "", feature: "", event: "", destination: "" });
  const [testDestination, setTestDestination] = useState("");
  const path = `/integrations/makerspace/${makerspaceId}`;
  const params = new URLSearchParams({ page: String(page) });
  Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
  const logs = useQuery({ queryKey: ["notification-deliveries", makerspaceId, params.toString()],
    queryFn: () => staffRequest<Page<Delivery>>(`${path}/delivery-logs?${params}`), refetchInterval: 30_000 });
  const destinations = useQuery({ queryKey: ["notification-delivery-destinations", makerspaceId],
    queryFn: () => staffRequest<Destination[]>(`/admin/makerspace/${makerspaceId}/notification-destinations`) });
  const refresh = () => client.invalidateQueries({ queryKey: ["notification-deliveries", makerspaceId] });
  const retry = useMutation({ mutationFn: (row: Delivery) => staffRequest<Delivery>(
    `${path}/delivery-logs/${row.kind}/${row.id}/retry`, { method: "POST", body: JSON.stringify({ generation: row.retry_generation }) },
  ), onSuccess: refresh });
  const test = useMutation({ mutationFn: () => staffRequest<TestResult>(`${path}/delivery-test`, {
    method: "POST", body: JSON.stringify(testDestination ? { destination_id: Number(testDestination) } : {}),
  }), onSuccess: refresh });
  const update = (key: keyof typeof filters, value: string) => { setFilters({ ...filters, [key]: value }); setPage(1); };
  const error = logs.error ?? retry.error ?? test.error ?? destinations.error;
  return <div className="space-y-5">
    <section className="desk-panel p-5">
      <h2 className="title-panel">Delivery logs</h2>
      <p className="mt-2 text-sm text-muted">Delivery attempts for this makerspace. Pending and sending rows are in flight; failed rows can be retried.</p>
      <div className="my-4 grid gap-3 sm:grid-cols-3">
        <label className="grid gap-1 text-sm">Channel<select className="desk-input" value={filters.channel} onChange={(e) => update("channel", e.target.value)}>
          <option value="">All channels</option>{["email", "telegram", "slack", "mattermost", "discord", "webhook", "native_push"].map((key) => <option key={key}>{key}</option>)}
        </select></label>
        <label className="grid gap-1 text-sm">Status<select className="desk-input" value={filters.status} onChange={(e) => update("status", e.target.value)}>
          <option value="">All statuses</option>{["pending", "sending", "sent", "failed", "skipped"].map((key) => <option key={key}>{key}</option>)}
        </select></label>
        <label className="grid gap-1 text-sm">Destination<select className="desk-input" value={filters.destination} onChange={(e) => update("destination", e.target.value)}>
          <option value="">All destinations</option>{destinations.data?.map((row) => <option key={row.id} value={row.id}>{row.label} ({row.channel})</option>)}
        </select></label>
        <label className="grid gap-1 text-sm">Family<select className="desk-input" value={filters.feature} onChange={(e) => update("feature", e.target.value)}>
          <option value="">All families</option>{["hardware_requests", "printing", "events", "bookings", "maintenance", "members", "payments", "stock", "certifications", "devices", "api_access"].map((key) => <option key={key}>{key}</option>)}
        </select></label>
        <label className="grid gap-1 text-sm">Event<input className="desk-input" maxLength={64} value={filters.event} onChange={(e) => update("event", e.target.value)} /></label>
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm">Test target<select className="desk-input" value={testDestination} onChange={(e) => setTestDestination(e.target.value)}>
          <option value="">Email to my account</option>{destinations.data?.filter((row) => row.is_active).map((row) => <option key={row.id} value={row.id}>{row.label} ({row.channel})</option>)}
        </select></label>
        <button className="desk-button-secondary" disabled={test.isPending} onClick={() => test.mutate()}>Send test</button>
        {test.data ? <p className="text-sm text-muted" role="status">Test {test.data.kind} #{test.data.id}: {test.data.status}. Refresh the log to see its final result.</p> : null}
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error.message}</p> : null}
      {logs.isLoading ? <p className="text-sm text-muted">Loading deliveries...</p> : null}
      {logs.data?.results.length === 0 ? <p className="text-sm text-muted">No deliveries match these filters.</p> : null}
      <ul className="space-y-3">{logs.data?.results.map((row) => <li key={`${row.kind}:${row.id}`} className="rounded-md border border-line p-3 text-sm">
        <p className="font-semibold text-ink">{row.channel} · {row.destination_label || "Personal devices"} · {row.status}</p>
        <p className="text-muted">{row.feature}.{row.event} · {new Date(row.created_at).toLocaleString()} · {row.attempts} attempt(s)</p>
        {row.error ? <p className="mt-1 break-words text-danger">{row.error}</p> : null}
        {row.status === "failed" ? <button className="desk-button-secondary mt-2" disabled={retry.isPending} onClick={() => retry.mutate(row)}>Retry failed delivery</button> : null}
      </li>)}</ul>
      <div className="mt-4 flex items-center gap-3">
        <button className="desk-button-ghost" disabled={!logs.data?.previous} onClick={() => setPage(page - 1)}>Previous</button>
        <span className="text-sm text-muted">Page {page} · {logs.data?.count ?? 0} deliveries</span>
        <button className="desk-button-ghost" disabled={!logs.data?.next} onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </section>
    <SuppressionAdmin makerspaceId={makerspaceId} />
  </div>;
}
