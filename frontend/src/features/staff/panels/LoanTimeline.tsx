import { useState } from "react";

import { useStaffGet } from "./shared";

type Actor = { username: string; role: string };
type TimelineEvent = {
  kind: string;
  at: string;
  actor: Actor | null;
  detail: Record<string, unknown>;
  evidence_id: number | null;
};
type RequestTimelineResponse = { request_id: number; limit: number; truncated: boolean; events: TimelineEvent[] };
type AssetGroup = { asset_id: number | null; asset_tag: string; serial_number: string; status: string; events: TimelineEvent[] };
type QuantitySummary = {
  loan_count: number;
  direct_loan_count: number;
  issued_quantity: number;
  returned_quantity: number;
  damaged_quantity: number;
  missing_quantity: number;
  active_quantity: number;
};
type ChainResponse = {
  product_id: number;
  product_name: string;
  tracking_mode: string;
  limit: number;
  truncated: boolean;
  events: TimelineEvent[];
  asset_groups: AssetGroup[];
  quantity_summary: QuantitySummary | null;
};

export function RequestTimelineBlock({ requestId }: { requestId: number }) {
  const timeline = useStaffGet<RequestTimelineResponse>(["request-timeline", requestId], `/admin/requests/${requestId}/timeline?limit=200`);
  return (
    <div className="mt-3 rounded-md border border-line bg-bg p-3">
      <h4 className="title-section">Loan timeline</h4>
      <QueryState loading={timeline.isLoading} error={timeline.error?.message} empty={!timeline.data?.events.length} emptyLabel="No timeline events yet." />
      {timeline.data ? <EventList events={timeline.data.events} truncated={timeline.data.truncated} /> : null}
    </div>
  );
}

export function ChainOfCustodyBlock({ productId }: { productId: number }) {
  const [open, setOpen] = useState(false);
  const chain = useStaffGet<ChainResponse>(["chain-of-custody", productId], `/admin/inventory/${productId}/chain-of-custody?limit=200`, open);
  return (
    <div className="grid gap-2 border-t border-line pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="title-section">Chain of custody</h3>
        <button className="desk-button-ghost" type="button" onClick={() => setOpen((value) => !value)}>{open ? "Hide" : "Open"}</button>
      </div>
      {open ? <QueryState loading={chain.isLoading} error={chain.error?.message} empty={!chain.data?.events.length} emptyLabel="No custody events yet." /> : null}
      {open && chain.data?.quantity_summary ? <QuantitySummaryView summary={chain.data.quantity_summary} /> : null}
      {open && chain.data?.asset_groups.length ? <AssetGroups groups={chain.data.asset_groups} /> : null}
      {open && chain.data ? <EventList events={chain.data.events} truncated={chain.data.truncated} /> : null}
    </div>
  );
}

function QueryState({ loading, error, empty, emptyLabel }: { loading: boolean; error?: string; empty: boolean; emptyLabel: string }) {
  if (loading) return <p className="text-sm text-muted">Loading...</p>;
  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (empty) return <p className="text-sm text-muted">{emptyLabel}</p>;
  return null;
}

function AssetGroups({ groups }: { groups: AssetGroup[] }) {
  return (
    <div className="grid gap-2">
      {groups.map((group) => (
        <div key={group.asset_id ?? group.asset_tag} className="rounded-md border border-line bg-surface p-2 text-xs">
          <p className="font-semibold text-ink">{group.asset_tag || `Asset #${group.asset_id}`} <span className="font-normal text-muted">{group.status}</span></p>
          <p className="text-muted">{group.events.map((event) => humanize(String(event.detail.outcome ?? event.kind))).join(" | ")}</p>
        </div>
      ))}
    </div>
  );
}

function QuantitySummaryView({ summary }: { summary: QuantitySummary }) {
  const parts = [
    `${summary.loan_count} reviewed loans`,
    `${summary.direct_loan_count} direct loans`,
    `${summary.issued_quantity} issued`,
    `${summary.returned_quantity} returned`,
    `${summary.damaged_quantity} damaged`,
    `${summary.missing_quantity} missing`,
    `${summary.active_quantity} active`,
  ];
  return <p className="text-xs text-muted">{parts.join(" | ")}</p>;
}

function EventList({ events, truncated }: { events: TimelineEvent[]; truncated: boolean }) {
  if (!events.length) return null;
  return (
    <ul className="eyebrow mt-2 grid gap-1">
      {events.map((event, index) => (
        <li key={`${event.kind}-${String(event.detail.id ?? index)}-${event.at}`} className="rounded-md border border-line bg-surface px-2 py-1">
          <span className="font-medium text-ink">{humanize(event.kind)}</span> on {formatDate(event.at)}
          {event.actor ? ` by ${formatActor(event.actor)}` : ""}
          {event.evidence_id ? ` | evidence #${event.evidence_id}` : ""}
          <DetailText detail={event.detail} />
        </li>
      ))}
      {truncated ? <li className="text-muted">History truncated at the requested limit.</li> : null}
    </ul>
  );
}

function DetailText({ detail }: { detail: Record<string, unknown> }) {
  const parts = ["product_name", "asset_tag", "outcome", "context", "issue_type", "quantity", "remark", "note"]
    .map((key) => detail[key])
    .filter((value) => value !== undefined && value !== null && value !== "")
    .map(String);
  return parts.length ? <span> | {parts.join(" | ")}</span> : null;
}

function formatActor(actor: Actor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (match) => match.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
