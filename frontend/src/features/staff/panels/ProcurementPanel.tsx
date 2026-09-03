import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import { Field, Metric } from "../../../components/ui";
import { downloadStaffFile, staffRequest } from "../../../lib/api";
import {
  groupProcurementRows,
  ProcurementRow,
  itemTotal,
  labelStatus,
  statusOptions,
  type Kind,
  type ToBuyItem,
  type ToBuyStatus,
} from "./ProcurementPanelRows";
import {
  procurementMachineTypeOptions,
  procurementMachineTypeRequired,
  type ProcurementMachineTypeOptions,
} from "./ProcurementPanelTypes";
import { ProcurementMoveModal } from "./ProcurementMoveModal";
import { Panel, type Makerspace, useStaffGet } from "./shared";

type StatusFilter = "all" | ToBuyStatus;
type UpdateVariables = { id: number; payload: { status: ToBuyStatus; vendor_name: string; actual_unit_cost: number | null } };

type Form = {
  name: string;
  quantity: string;
  link: string;
  estimated_unit_cost: string;
  vendor_name: string;
  actual_unit_cost: string;
  kind: Kind;
  machine_type: string;
};

const emptyForm: Form = {
  name: "",
  quantity: "1",
  link: "",
  estimated_unit_cost: "",
  vendor_name: "",
  actual_unit_cost: "",
  kind: "hardware",
  machine_type: "",
};

type ProcurementPanelProps = {
  makerspace: Makerspace;
  canChooseKind?: boolean;
};

export function ProcurementPanel({
  makerspace,
  canChooseKind = false,
}: ProcurementPanelProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Form>(emptyForm);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("requested");
  const [moveTarget, setMoveTarget] = useState<ToBuyItem | null>(null);
  const base = `/procurement/makerspace/${makerspace.id}/to-buy`;
  const statusParam = statusFilter === "all" ? "" : `&status=${statusFilter}`;
  const queryKey = ["procurement", makerspace.id, statusFilter];
  const items = useStaffGet<ToBuyItem[]>(queryKey, `${base}?limit=200${statusParam}`);
  const machineTypes = useStaffGet<ProcurementMachineTypeOptions>(
    ["procurement-machine-types", makerspace.id, form.kind],
    `${base}/machine-types?kind=${form.kind}`,
  );
  const typeOptions = procurementMachineTypeOptions(machineTypes.data);
  // Server-derived, and it already accounts for the stream, so it needs no local
  // `createsPrintingByDefault` qualifier.
  const requiresMachineType = procurementMachineTypeRequired(machineTypes.data);
  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["procurement", makerspace.id] }),
    queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
  ]);

  const create = useMutation({
    mutationFn: () => {
      const path = canChooseKind ? `${base}?kind=${form.kind}` : base;
      return staffRequest(path, {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          quantity: Number(form.quantity) || 1,
          link: form.link,
          estimated_unit_cost: form.estimated_unit_cost ? Number(form.estimated_unit_cost) : null,
          vendor_name: form.vendor_name,
          actual_unit_cost: form.actual_unit_cost ? Number(form.actual_unit_cost) : null,
          machine_type: form.machine_type ? Number(form.machine_type) : null,
        }),
      });
    },
    onSuccess: () => {
      setForm(emptyForm);
      invalidate();
    },
  });

  const update = useMutation({
    mutationFn: (vars: UpdateVariables) =>
      staffRequest(`/procurement/to-buy/${vars.id}`, {
        method: "PATCH",
        body: JSON.stringify(vars.payload),
      }),
    onSuccess: invalidate,
  });

  const remove = useMutation({
    mutationFn: (id: number) => staffRequest(`/procurement/to-buy/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const exportToBuy = useMutation({
    mutationFn: (format: "csv" | "xlsx") => {
      const params = new URLSearchParams({ format });
      if (statusFilter !== "all") params.set("status", statusFilter);
      return downloadStaffFile(`${base}/export?${params.toString()}`, `to-buy-${makerspace.slug}.${format}`);
    },
  });

  const rows = items.data ?? [];
  const visibleEstimatedTotal = rows.reduce((sum, item) => sum + itemTotal(item, "estimated"), 0);
  const openBudget = rows.filter((item) => !["received", "cancelled"].includes(item.status)).reduce((sum, item) => sum + itemTotal(item, "estimated"), 0);
  const receivedTotal = rows.filter((item) => item.status === "received").reduce((sum, item) => sum + itemTotal(item, "actual"), 0);

  return (
    <Panel title="To Buy">
      <p className="mb-3 text-xs text-muted">
        Shopping list for {makerspace.name}. Track requested, approved, ordered, and received purchases with receipts.
      </p>

      <form className="grid gap-2 sm:grid-cols-2 xl:grid-cols-8" onSubmit={(event) => { event.preventDefault(); if (form.name.trim() && (!requiresMachineType || form.machine_type)) create.mutate(); }}>
        <Field label="Item name" className="xl:col-span-2"><input className="desk-input xl:col-span-2" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Quantity"><input className="desk-input" type="number" min={1} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
        <Field label="Link (optional)"><input className="desk-input" value={form.link} onChange={(e) => setForm({ ...form, link: e.target.value })} /></Field>
        <Field label="Estimated unit cost"><input className="desk-input" type="number" min={0} step="0.01" value={form.estimated_unit_cost} onChange={(e) => setForm({ ...form, estimated_unit_cost: e.target.value })} /></Field>
        <Field label="Vendor"><input className="desk-input" value={form.vendor_name} onChange={(e) => setForm({ ...form, vendor_name: e.target.value })} /></Field>
        <Field label="Actual unit cost"><input className="desk-input" type="number" min={0} step="0.01" value={form.actual_unit_cost} onChange={(e) => setForm({ ...form, actual_unit_cost: e.target.value })} /></Field>
        <label className="eyebrow grid gap-1">
          Machine type
          <select
            className="desk-input"
            value={form.machine_type}
            onChange={(event) => setForm({ ...form, machine_type: event.target.value })}
            required={requiresMachineType}
          >
            <option value="">{requiresMachineType ? "Select a type" : "Unassigned"}</option>
            {typeOptions.map((machineType) => (
              <option key={machineType.id} value={machineType.id}>{machineType.name}</option>
            ))}
          </select>
          {requiresMachineType && !machineTypes.isLoading && !typeOptions.length ? (
            <span className="normal-case tracking-normal text-danger">No machine types are linked to your role.</span>
          ) : null}
        </label>
        {canChooseKind ? <KindSelect value={form.kind} onChange={(kind) => setForm({ ...form, kind })} /> : <AddButton disabled={create.isPending || !form.name.trim() || (requiresMachineType && !form.machine_type)} label="Add" />}
        {canChooseKind ? <AddButton disabled={create.isPending || !form.name.trim() || (requiresMachineType && !form.machine_type)} label="Add item" className="xl:col-span-8" /> : null}
      </form>
      <MutationErrors create={create.error} update={update.error} remove={remove.error} exportError={exportToBuy.error} />

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Visible estimated total" value={formatAmount(visibleEstimatedTotal)} />
          <Metric label="Open budget" value={formatAmount(openBudget)} />
          <Metric label="Received actual total" value={formatAmount(receivedTotal)} />
          <label className="eyebrow grid gap-1">
            Status
            <select className="desk-input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="all">All</option>
              {statusOptions.map((status) => <option key={status} value={status}>{labelStatus(status)}</option>)}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap gap-2 justify-self-start lg:justify-self-end">
          <button className="desk-button-ghost" type="button" disabled={exportToBuy.isPending} onClick={() => exportToBuy.mutate("csv")}>Export CSV</button>
          <button className="desk-button-ghost" type="button" disabled={exportToBuy.isPending} onClick={() => exportToBuy.mutate("xlsx")}>Export XLSX</button>
        </div>
      </div>
      <ProcurementTable rows={rows} items={items} update={update} remove={remove} invalidate={invalidate} makerspaceSlug={makerspace.slug} onMove={setMoveTarget} />
      <ProcurementMoveModal item={moveTarget} makerspace={makerspace} onClose={() => setMoveTarget(null)} onMoved={invalidate} />
    </Panel>
  );
}

function ProcurementTable({ rows, items, update, remove, invalidate, makerspaceSlug, onMove }: { rows: ToBuyItem[]; items: UseQueryResult<ToBuyItem[], Error>; update: UseMutationResult<unknown, Error, UpdateVariables>; remove: UseMutationResult<unknown, Error, number>; invalidate: () => void; makerspaceSlug: string; onMove: (item: ToBuyItem) => void }) {
  if (items.isFetching && !items.isLoading) return <p className="mt-2 text-xs text-muted">Refreshing list...</p>;
  if (items.isLoading) return <p className="mt-3 text-sm text-muted">Loading...</p>;
  if (items.error) return <p className="mt-3 text-sm text-danger">{items.error instanceof Error ? items.error.message : "Unable to load list."}</p>;
  if (!rows.length) return <p className="mt-3 text-sm text-muted">Nothing on the list yet.</p>;
  return (
    <div className="mt-3 max-h-[32rem] overflow-x-auto overflow-y-auto rounded-md border border-line">
      <table className="min-w-[1180px] divide-y divide-line text-left text-sm">
        <thead className="eyebrow sticky top-0 bg-surface">
          <tr>{["kind", "item", "qty", "link", "est.", "vendor", "actual", "purchaser", "ordered", "received", "receipts", "status", "moved", ""].map((header) => <th scope={header ? "col" : undefined} key={header} className="whitespace-nowrap px-3 py-2">{header}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line bg-bg text-ink">
          {groupProcurementRows(rows).map((group) => (
            <GroupedRows
              key={group.key}
              label={group.label}
              rows={group.rows}
              makerspaceSlug={makerspaceSlug}
              update={update}
              remove={remove}
              invalidate={invalidate}
              onMove={onMove}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupedRows({ label, rows, makerspaceSlug, update, remove, invalidate, onMove }: { label: string; rows: ToBuyItem[]; makerspaceSlug: string; update: UseMutationResult<unknown, Error, UpdateVariables>; remove: UseMutationResult<unknown, Error, number>; invalidate: () => void; onMove: (item: ToBuyItem) => void }) {
  return <>
    <tr className="bg-surface"><th scope="row" className="eyebrow px-3 py-2" colSpan={14}>{label}</th></tr>
    {rows.map((item) => <ProcurementRow key={item.id} item={item} makerspaceSlug={makerspaceSlug} updatePending={update.isPending} deletePending={remove.isPending} onSave={(draft) => update.mutate({ id: item.id, payload: { status: draft.status, vendor_name: draft.vendor_name, actual_unit_cost: draft.actual_unit_cost ? Number(draft.actual_unit_cost) : null } })} onDelete={() => remove.mutate(item.id)} onMove={() => onMove(item)} onReceiptsChanged={invalidate} />)}
  </>;
}

function KindSelect({ value, onChange }: { value: Kind; onChange: (kind: Kind) => void }) {
  return <Field label="Kind"><select className="desk-input" value={value} onChange={(e) => onChange(e.target.value as Kind)}><option value="hardware">Hardware</option><option value="printing">Printing</option></select></Field>;
}

function AddButton({ disabled, label, className = "" }: { disabled: boolean; label: string; className?: string }) {
  return <button className={`desk-button-primary ${className}`} type="submit" disabled={disabled}>{label}</button>;
}

function MutationErrors({ create, update, remove, exportError }: { create: unknown; update: unknown; remove: unknown; exportError: unknown }) {
  const errors = [[create, "Could not add item."], [update, "Could not update item."], [remove, "Could not delete item."], [exportError, "Could not export list."]] as const;
  return <>{errors.map(([error, fallback]) => error ? <p key={fallback} className="mt-2 text-sm text-danger">{error instanceof Error ? error.message : fallback}</p> : null)}</>;
}

function formatAmount(value: number) {
  return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
