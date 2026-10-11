import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { staffRequest } from "../../../lib/api";
import { useUrlListState } from "../../../lib/useUrlListState";
import { Pagination } from "../../../components/ui/Pagination";
import { collectionResults, getMachineTypes, machineKeys } from "../machinesApi";
import { machineTypeSegment, staffTabPath } from "../staffTabs";
import { Panel } from "./shared";

const statuses: Record<string, string> = { pending_prints: "pending", active_prints: "in_progress", prints_awaiting_collection: "completed" };
const labels: Record<string, string> = { pending_prints: "Pending prints", active_prints: "Active prints", prints_awaiting_collection: "Ready to collect", maintenance_overdue: "Maintenance overdue" };
type Schedule = { id: number; machine_id: number; machine_name: string; description: string; next_due: string };
type Job = { id: number; title: string; status: string };

export function isDashboardMachineQueue(queue: string) { return Object.prototype.hasOwnProperty.call(labels, queue); }
export function DashboardMachineQueue({ makerspaceId, slug, single, guest, enabled }: { makerspaceId: number; slug?: string | null; single: boolean; guest: boolean; enabled: boolean }) {
  const list = useUrlListState({ work_queue: "", page: "1" });
  const queue = list.values.work_queue;
  const maintenance = queue === "maintenance_overdue";
  const types = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId), enabled: enabled && !maintenance });
  const printer = collectionResults(types.data).find(type => type.is_builtin && type.slug === "3d_printer" && type.makerspace === null);
  const jobs = useQuery({ queryKey: ["dashboard-print-queue", makerspaceId, queue, printer?.id], queryFn: () => staffRequest<Job[]>(`/admin/makerspaces/${makerspaceId}/machine-service/requests?status=${statuses[queue]}&machine_type_id=${printer!.id}`), enabled: enabled && !maintenance && !!printer });
  const schedules = useQuery({ queryKey: ["dashboard-maintenance-queue", makerspaceId, list.page], queryFn: () => staffRequest<{ count: number; results: Schedule[] }>(`/admin/makerspace/${makerspaceId}/maintenance-overdue?page=${list.page}`), enabled: enabled && maintenance });
  const href = staffTabPath("machines", guest, slug, single);
  const error = types.error ?? jobs.error ?? schedules.error;
  const scheduleRows = enabled && maintenance ? schedules.data?.results : undefined;
  const jobRows = enabled && !maintenance ? jobs.data : undefined;
  return <Panel title={labels[queue]}>
    <Link className="desk-button-ghost inline-flex mb-4" to={href}>All machines</Link>
    {!enabled ? <p role="alert">This queue is unavailable because its module is disabled.</p> : null}
    {enabled && (types.isLoading || jobs.isLoading || schedules.isLoading) ? <p role="status">Loading work list…</p> : null}
    {enabled && error ? <p role="alert" className="text-sm text-danger">{error.message}</p> : null}
    {enabled && !maintenance && types.isSuccess && !printer ? <p>No built-in printer type is available in your scope.</p> : null}
    <ul className="grid gap-3">{scheduleRows?.map(row => <li key={row.id} className="desk-panel p-3"><Link className="underline" to={`${href}?machine=${row.machine_id}&detail_tab=Maintenance`}>{row.machine_name}: {row.description}</Link><p className="text-sm text-muted">Due {row.next_due}</p></li>)}{jobRows?.map(row => <li key={row.id} className="desk-panel p-3"><p>{row.title} · {row.status.replace(/_/g, " ")}</p>{printer ? <Link className="desk-button-secondary mt-2 inline-flex" to={staffTabPath("machines", guest, slug, single, machineTypeSegment(printer))}>Open printer queue</Link> : null}</li>)}</ul>
    {(scheduleRows?.length === 0 || jobRows?.length === 0) ? <p className="text-sm text-muted">No work in this queue.</p> : null}
    {enabled && maintenance ? <Pagination page={list.page} totalPages={Math.max(1, Math.ceil((schedules.data?.count ?? 0) / 24))} count={schedules.data?.count ?? 0} pageSize={24} onChange={list.setPage} /> : null}
  </Panel>;
}
