import { useEffect, useState } from "react";

import { Badge } from "../../../components/ui";
import { ProcurementReceipts, type ToBuyReceipt } from "./ProcurementReceipts";

export type Kind = "hardware" | "printing";
export type ToBuyStatus = "requested" | "approved" | "ordered" | "received" | "cancelled";

export type ToBuyItem = {
  id: number;
  kind: Kind;
  machine_type: number | null;
  machine_type_name: string | null;
  name: string;
  quantity: number;
  link: string;
  status: ToBuyStatus;
  estimated_unit_cost: string | null;
  vendor_name: string;
  actual_unit_cost: string | null;
  purchaser_username: string | null;
  ordered_at: string | null;
  received_at: string | null;
  moved_to_inventory_at: string | null;
  resulting_product: number | null;
  resulting_pool: number | null;
  resulting_machine: number | null;
  source_pool: number | null;
  created_by_username: string | null;
  receipts: ToBuyReceipt[];
};

export type RowDraft = {
  status: ToBuyStatus;
  vendor_name: string;
  actual_unit_cost: string;
};

export const statusOptions: ToBuyStatus[] = ["requested", "approved", "ordered", "received", "cancelled"];

export type ProcurementGroup = {
  key: string;
  label: string;
  rows: ToBuyItem[];
};

export function groupProcurementRows(rows: ToBuyItem[]): ProcurementGroup[] {
  const groups = new Map<string, ProcurementGroup>();
  for (const item of rows) {
    const key = item.machine_type === null ? "unassigned" : `type-${item.machine_type}`;
    const label = item.machine_type_name ?? "Unassigned";
    const group = groups.get(key) ?? { key, label, rows: [] };
    group.rows.push(item);
    groups.set(key, group);
  }
  return [...groups.values()].sort((left, right) => {
    if (left.key === "unassigned") return 1;
    if (right.key === "unassigned") return -1;
    return left.label.localeCompare(right.label);
  });
}

export function ProcurementRow({ item, makerspaceSlug, updatePending, deletePending, onSave, onDelete, onMove, onReceiptsChanged }: {
  item: ToBuyItem;
  makerspaceSlug: string;
  updatePending: boolean;
  deletePending: boolean;
  onSave: (draft: RowDraft) => void;
  onDelete: () => void;
  onMove: () => void;
  onReceiptsChanged: () => void;
}) {
  const [draft, setDraft] = useState<RowDraft>(() => draftFromItem(item));

  useEffect(() => setDraft(draftFromItem(item)), [item]);

  return (
    <tr>
      <td className="px-3 py-2 text-xs uppercase text-muted">{item.kind}</td>
      <td className="px-3 py-2"><span className="block max-w-56 break-words">{item.name}</span>{item.source_pool ? <span className="mt-1 block"><Badge tone="warn">Auto - low stock</Badge></span> : null}</td>
      <td className="px-3 py-2">{item.quantity}</td>
      <td className="px-3 py-2"><ItemLink link={item.link} /></td>
      <td className="px-3 py-2">{item.estimated_unit_cost ?? "-"}</td>
      <td className="px-3 py-2"><input className="desk-input w-36" value={draft.vendor_name} onChange={(event) => setDraft({ ...draft, vendor_name: event.target.value })} /></td>
      <td className="px-3 py-2"><input className="desk-input w-28" type="number" min={0} step="0.01" value={draft.actual_unit_cost} onChange={(event) => setDraft({ ...draft, actual_unit_cost: event.target.value })} /></td>
      <td className="px-3 py-2 text-muted"><span className="block max-w-36 break-words">{item.purchaser_username ?? "-"}</span></td>
      <td className="px-3 py-2 text-xs text-muted">{formatDateTime(item.ordered_at)}</td>
      <td className="px-3 py-2 text-xs text-muted">{formatDateTime(item.received_at)}</td>
      <td className="px-3 py-2"><ProcurementReceipts itemId={item.id} receipts={item.receipts ?? []} onChanged={onReceiptsChanged} /></td>
      <td className="px-3 py-2">
        <select className="desk-input w-32" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as ToBuyStatus })}>
          {statusOptions.map((status) => <option key={status} value={status}>{labelStatus(status)}</option>)}
        </select>
      </td>
      <td className="px-3 py-2 text-xs text-muted"><MoveState item={item} makerspaceSlug={makerspaceSlug} /></td>
      <td className="px-3 py-2 text-right">
        <div className="flex flex-col gap-2">
          {item.status === "received" && !item.moved_to_inventory_at ? <button type="button" className="desk-button bg-success text-on-success" onClick={onMove}>Move</button> : null}
          <button type="button" className="desk-button" disabled={updatePending || !isDraftChanged(item, draft)} onClick={() => onSave(draft)}>Save</button>
          <button type="button" className="desk-button" disabled={deletePending} onClick={onDelete}>Delete</button>
        </div>
      </td>
    </tr>
  );
}

function MoveState({ item, makerspaceSlug }: { item: ToBuyItem; makerspaceSlug: string }) {
  if (!item.moved_to_inventory_at) return <>-</>;
  if (item.resulting_product) {
    return <a className="text-accent-ink underline" href={`/m/${makerspaceSlug}/admin/inventory`}>Inventory #{item.resulting_product}</a>;
  }
  if (item.resulting_pool) return <>Pool #{item.resulting_pool}</>;
  if (item.resulting_machine) return <>Machine #{item.resulting_machine}</>;
  return <>Moved</>;
}

function ItemLink({ link }: { link: string }) {
  const href = safeHref(link);
  if (href) return <a className="text-accent-ink underline" href={href} target="_blank" rel="noreferrer">link</a>;
  if (link) return <span className="block max-w-56 break-all text-muted" title={link}>{link}</span>;
  return <>-</>;
}

function safeHref(link: string): string | null {
  return /^https?:\/\//i.test(link) ? link : null;
}

function draftFromItem(item: ToBuyItem): RowDraft {
  return {
    status: item.status,
    vendor_name: item.vendor_name ?? "",
    actual_unit_cost: item.actual_unit_cost ?? "",
  };
}

function isDraftChanged(item: ToBuyItem, draft: RowDraft) {
  return item.status !== draft.status || (item.vendor_name ?? "") !== draft.vendor_name || (item.actual_unit_cost ?? "") !== draft.actual_unit_cost;
}

export function itemTotal(item: ToBuyItem, mode: "estimated" | "actual") {
  const raw = mode === "actual" ? item.actual_unit_cost ?? item.estimated_unit_cost : item.estimated_unit_cost;
  const unitCost = Number(raw ?? 0);
  return Number.isFinite(unitCost) ? unitCost * item.quantity : 0;
}

export function labelStatus(status: ToBuyStatus) {
  return status.charAt(0).toUpperCase() + status.slice(1).replace("_", " ");
}

function formatDateTime(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
