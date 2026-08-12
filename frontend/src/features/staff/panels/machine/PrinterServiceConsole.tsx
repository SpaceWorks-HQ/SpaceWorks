import { useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MachineServiceRequest, PrinterPool, PrinterServiceReport, TypedManualUsageResponse } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { machineKeys } from "../../machinesApi";
import type { Machine, MachineType } from "../../machinesApi";
import { useStaffGet } from "../shared";
import { clearedActionDraft } from "./serviceDrafts";
import type { ServiceActionName, ServiceDraft } from "./serviceDrafts";
import { poolQueryKey, usablePools } from "./servicePools";

type Props = {
  makerspaceId: number;
  canManage: boolean;
  printingEnabled: boolean;
  machineType: MachineType;
  machines: Machine[];
  pools: PrinterPool[];
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
// Mirrors backend `printer_capabilities.PRINTER_SLUG`.
const PRINTER_SLUG = "3d_printer";

export function PrinterServiceConsole({ makerspaceId, canManage, printingEnabled, machineType, machines, pools, draft, setDraft }: Props) {
  const queryClient = useQueryClient();
  // Filter by the stable machine-type ID, not the slug: slugs are not unique across the
  // global/tenant split, so a makerspace-local type sharing a built-in's slug would pull in
  // the other type's jobs and let a manager mutate them from the wrong section.
  const typeFilter = `machine_type_id=${machineType.id}`;
  const requests = useStaffGet<MachineServiceRequest[]>(
    ["machine-service-requests", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/requests?${typeFilter}`,
    canManage && printingEnabled,
  );
  const manualUsage = useStaffGet<TypedManualUsageResponse[]>(
    ["machine-service-manual", makerspaceId, machineType.id],
    `/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage?${typeFilter}`,
    canManage,
  );
  const report = useStaffGet<PrinterServiceReport>(
    ["printer-service-report", makerspaceId, machineType.id],
    // The REPORT endpoint is a different contract: it discriminates on the `machine_type`
    // SLUG to decide whether to emit `printer_metrics`. Sending the id instead silently
    // returns the generic report, and the render below dereferences `printer_metrics`, so
    // the whole Machines panel dies in its error boundary. This console only ever mounts
    // for the global built-in printer, so the literal slug is exactly right here.
    `/admin/makerspace/${makerspaceId}/machine-service-report?machine_type=${PRINTER_SLUG}`,
    canManage && printingEnabled,
  );
  const printerUsage = useMemo(
    () => (manualUsage.data ?? []).filter((entry) => entry.metering_unit === "weight"),
    [manualUsage.data],
  );
  const actionPools = usablePools(pools, "grams", draft.actionValues.machine_id);
  const manualPools = usablePools(pools, "grams", draft.manual.machine_id);

  const invalidate = () => void Promise.all([
    queryClient.invalidateQueries({ queryKey: ["machine-service-requests", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: ["machine-service-manual", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: ["printer-service-report", makerspaceId, machineType.id] }),
    queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) }),
    // Service transitions change the assigned machine's status, and manual usage its
    // usage hours; without this the integrated machine row and the status filter
    // stay stale until an unrelated refetch.
    queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
  ]);
  const submitManual = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspaces/${makerspaceId}/machine-service/typed-manual-usage`, {
      method: "POST",
      body: JSON.stringify({
        machine_id: Number(draft.manual.machine_id),
        consumable_pool_id: draft.manual.consumable_pool_id ? Number(draft.manual.consumable_pool_id) : null,
        duration_minutes: Number(draft.manual.duration_minutes),
        grams: draft.manual.quantity || undefined,
        outcome: draft.manual.outcome,
        percent_complete: Number(draft.manual.percent_complete),
        reason: draft.manual.reason || undefined,
        note: draft.manual.note || undefined,
      }),
    }),
    onSuccess: () => {
      setDraft((current) => ({ ...current, manual: { ...current.manual, machine_id: "", consumable_pool_id: "", duration_minutes: "", quantity: "", outcome: "success", percent_complete: "100", reason: "", note: "" } }));
      invalidate();
    },
  });
  const runAction = useMutation({
    mutationFn: () => {
      if (!draft.action) throw new Error("Choose an action.");
      return staffRequest(`/admin/machine-service/requests/${draft.action.id}/${draft.action.name}`, {
        method: "POST",
        body: JSON.stringify(actionBody(draft.action.name, draft.actionValues)),
      });
    },
    onSuccess: () => {
      setDraft(clearedActionDraft);
      invalidate();
    },
  });

  if (!canManage) return null;
  return (
    <div className="grid gap-4 border-t border-line p-3">
      {printingEnabled ? (
        <Subsection title="3D-printer queue">
          <p className="mb-3 text-sm text-muted">Accept jobs, reserve filament, start work, reconcile actual grams, then complete, fail, collect, or reprint.</p>
          <div className="grid gap-2">
            {requests.data?.map((request) => (
              <article className="rounded-md border border-line bg-surface p-3" key={request.id}>
                <div className="flex flex-wrap items-center justify-between gap-2"><strong>{request.title}</strong><span>{request.status.replace("_", " ")}</span></div>
                <p className="mt-1 text-xs text-muted">Planned {request.planned_grams}g</p>
                <div className="mt-2 flex flex-wrap gap-2"><ServiceActions request={request} onAction={(name) => setDraft((current) => ({ ...current, action: { id: request.id, name } }))} /></div>
              </article>
            )) ?? <p className="text-sm text-muted">Loading printer queue…</p>}
          </div>
          {draft.action ? <ActionForm action={draft.action.name} values={draft.actionValues} setValues={(actionValues) => setDraft((current) => ({ ...current, actionValues }))} printers={machines} pools={actionPools} pending={runAction.isPending} onCancel={() => setDraft((current) => ({ ...current, action: null }))} onSubmit={() => runAction.mutate()} /> : null}
        </Subsection>
      ) : null}
      <Subsection title="Manual usage">
        <ManualUsageForm draft={draft} setDraft={setDraft} printers={machines} pools={manualPools} pending={submitManual.isPending} onSubmit={() => submitManual.mutate()} />
        <div className="mt-3 grid gap-2">{printerUsage.map((entry) => <p className="rounded-md border border-line p-2 font-mono text-sm" key={entry.id}>{entry.outcome} · {entry.consumed_grams}g · {entry.duration_minutes} min{entry.outcome === "failed" ? ` · ${entry.percent_complete}%` : ""}</p>)}</div>
      </Subsection>
      {printingEnabled ? (
        <Subsection title="Printer reports">
          <div className="grid gap-2 md:grid-cols-2">
            {report.data?.printer_metrics.map((metric) => <p className="rounded-md border border-line p-3 text-sm" key={`${metric.makerspace_id ?? makerspaceId}:${metric.machine_id}`}><strong>{metric.machine_name}</strong><span className="mt-1 block text-xs text-muted">{metric.completed_hours}h complete - {metric.failed_partial_hours}h failed - {metric.manual_hours}h manual - {metric.consumed_grams}g used</span></p>)}
            {report.data && report.data.printer_metrics.length === 0 ? <p className="text-sm text-muted">No completed printer activity yet.</p> : null}
          </div>
        </Subsection>
      ) : null}
      <ErrorBlock error={[requests.error, manualUsage.error, report.error, submitManual.error, runAction.error].find((item) => item instanceof Error)} />
    </div>
  );
}

function actionBody(action: ServiceActionName, values: ServiceDraft["actionValues"]) {
  if (action === "accept") return { estimated_minutes: Number(values.estimated_minutes), planned_grams: values.planned_quantity || undefined };
  if (action === "start") return { machine_id: values.machine_id ? Number(values.machine_id) : null, consumable_pool_id: values.consumable_pool_id ? Number(values.consumable_pool_id) : undefined, estimated_minutes: Number(values.estimated_minutes), planned_grams: values.planned_quantity || undefined };
  if (action === "complete") return { actual_minutes: Number(values.actual_minutes), actual_grams: values.actual_quantity || undefined };
  if (action === "fail") return { actual_minutes: Number(values.actual_minutes), actual_grams: values.actual_quantity || undefined, percent_complete: Number(values.percent_complete), reason: values.reason };
  return action === "reject" ? { reason: values.reason } : {};
}

function ServiceActions({ request, onAction }: { request: MachineServiceRequest; onAction: (name: ServiceActionName) => void }) {
  if (request.status === "pending") return <><button className="desk-button-success" onClick={() => onAction("accept")}>Accept</button><button className="desk-button-danger" onClick={() => onAction("reject")}>Reject</button></>;
  if (request.status === "accepted") return <button className="desk-button-primary" onClick={() => onAction("start")}>Start</button>;
  if (request.status === "in_progress") return <><button className="desk-button-success" onClick={() => onAction("complete")}>Complete</button><button className="desk-button-danger" onClick={() => onAction("fail")}>Fail</button></>;
  if (request.status === "completed") return <button className="desk-button-success" onClick={() => onAction("collect")}>Collect</button>;
  return request.status === "failed" ? <button className="desk-button-warn" onClick={() => onAction("reprint")}>Reprint</button> : null;
}

function ActionForm({ action, values, setValues, printers, pools, pending, onCancel, onSubmit }: { action: ServiceActionName; values: ServiceDraft["actionValues"]; setValues: (values: ServiceDraft["actionValues"]) => void; printers: Machine[]; pools: PrinterPool[]; pending: boolean; onCancel: () => void; onSubmit: () => void }) {
  const input = (key: keyof typeof values, label: string) => <label className="eyebrow grid gap-1">{label}<input className={`desk-input ${focusRing}`} value={values[key]} onChange={(event) => setValues({ ...values, [key]: event.target.value })} /></label>;
  return <div className="mt-3 rounded-md border border-accent bg-bg p-3"><h5 className="title-section capitalize">{action}</h5><div className="mt-2 grid gap-2 md:grid-cols-3">{action === "start" ? <><select aria-label="Printer" className={`desk-input ${focusRing}`} value={values.machine_id} onChange={(event) => setValues({ ...values, machine_id: event.target.value, consumable_pool_id: "" })}><option value="">Printer</option>{printers.map((printer) => <option key={printer.id} value={printer.id}>{printer.name}</option>)}</select><select aria-label="Pool" className={`desk-input ${focusRing}`} value={values.consumable_pool_id} onChange={(event) => setValues({ ...values, consumable_pool_id: event.target.value })}><option value="">Pool</option>{pools.map((pool) => <option key={pool.id} value={pool.id}>{pool.material} {pool.color}</option>)}</select>{input("estimated_minutes", "Estimated minutes")}{input("planned_quantity", "Planned grams")}</> : null}{action === "accept" ? <>{input("estimated_minutes", "Estimated minutes")}{input("planned_quantity", "Planned grams")}</> : null}{action === "complete" || action === "fail" ? <>{input("actual_minutes", "Actual minutes")}{input("actual_quantity", "Actual grams")}{action === "fail" ? <>{input("percent_complete", "Percent complete")}{input("reason", "Reason")}</> : null}</> : null}{action === "reject" ? input("reason", "Reason") : null}</div><div className="mt-2 flex gap-2"><button className="desk-button-success" disabled={pending} onClick={onSubmit}>Confirm</button><button className="desk-button-ghost" onClick={onCancel}>Cancel</button></div></div>;
}

function ManualUsageForm({ draft, setDraft, printers, pools, pending, onSubmit }: { draft: ServiceDraft; setDraft: Props["setDraft"]; printers: Machine[]; pools: PrinterPool[]; pending: boolean; onSubmit: () => void }) {
  const manual = draft.manual;
  const update = (patch: Partial<typeof manual>) => setDraft((current) => ({ ...current, manual: { ...current.manual, ...patch } }));
  return <div className="grid gap-2 md:grid-cols-4"><select aria-label="Manual usage printer" className={`desk-input ${focusRing}`} value={manual.machine_id} onChange={(event) => update({ machine_id: event.target.value, consumable_pool_id: "" })}><option value="">Printer</option>{printers.map((machine) => <option value={machine.id} key={machine.id}>{machine.name}</option>)}</select><select aria-label="Manual usage pool" className={`desk-input ${focusRing}`} value={manual.consumable_pool_id} onChange={(event) => update({ consumable_pool_id: event.target.value })}><option value="">No pool</option>{pools.map((pool) => <option value={pool.id} key={pool.id}>{pool.material} {pool.color}</option>)}</select><input aria-label="Manual usage minutes" className={`desk-input ${focusRing}`} placeholder="Minutes" type="number" value={manual.duration_minutes} onChange={(event) => update({ duration_minutes: event.target.value })} /><input aria-label="Manual usage grams" className={`desk-input ${focusRing}`} placeholder="Grams" type="number" value={manual.quantity} onChange={(event) => update({ quantity: event.target.value })} /><select aria-label="Manual usage outcome" className={`desk-input ${focusRing}`} value={manual.outcome} onChange={(event) => update({ outcome: event.target.value })}><option value="success">Success</option><option value="failed">Failed</option></select>{manual.outcome === "failed" ? <><input aria-label="Percent complete" className={`desk-input ${focusRing}`} placeholder="Percent complete" type="number" value={manual.percent_complete} onChange={(event) => update({ percent_complete: event.target.value })} /><input aria-label="Failure reason" className={`desk-input ${focusRing}`} placeholder="Failure reason" value={manual.reason} onChange={(event) => update({ reason: event.target.value })} /></> : null}<input aria-label="Manual usage note" className={`desk-input ${focusRing}`} placeholder="Note" value={manual.note} onChange={(event) => update({ note: event.target.value })} /><button className="desk-button-primary" disabled={!manual.machine_id || !manual.duration_minutes || pending} onClick={onSubmit}>Log usage</button></div>;
}

function Subsection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h4 className="title-section mb-2">{title}</h4>{children}</section>;
}

function ErrorBlock({ error }: { error: unknown }) {
  return error instanceof Error ? <p className="text-sm text-danger">{error.message}</p> : null;
}
