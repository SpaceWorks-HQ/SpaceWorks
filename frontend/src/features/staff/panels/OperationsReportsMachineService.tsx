import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { Panel, type Makerspace, useStaffGet } from "./shared";

type Scoped = { makerspace_id?: number };
type Status = Scoped & { submitted: number; accepted: number; in_progress: number; completed: number; collected: number; rejected: number; failed: number };
type Machine = Scoped & { machine_id: number; machine_name: string; machine_type: string | null; request_count: number; completed_count: number; failed_count: number; completed_hours: number; failed_partial_hours: number; total_recorded_service_hours: number; failure_rate: number | null };
type Consumption = Scoped & { machine_id: number; machine_name: string; measurement: "count" | "grams"; product_id: number | null; product_label: string; completed_amount: string; failed_partial_amount: string; total_used: string };
type Failure = Scoped & { machine_id: number; machine_name: string; outcome: string; failed_count: number; failed_partial_hours: number; failed_count_amount: string; failed_grams_amount: string };
type Report = { status_totals: Status[]; machines: Machine[]; consumption: Consumption[]; failure_summary: Failure[] };

export function OperationsReportsMachineService({ makerspace, aggregate, canManageMachines, startDate, endDate, makerspaceName }: {
  makerspace: Makerspace;
  aggregate: boolean;
  canManageMachines: boolean;
  startDate: string;
  endDate: string;
  makerspaceName: (id: number) => string;
}) {
  const enabled = canManageMachines && (aggregate || (makerspace.enabled_modules ?? []).includes("machine_service"));
  const base = aggregate ? "/admin/machine-service-report" : `/admin/makerspace/${makerspace.id}/machine-service-report`;
  const query = new URLSearchParams();
  if (startDate) query.set("start", startDate);
  if (endDate) query.set("end", endDate);
  const report = useStaffGet<Report>(["machine-service-report", aggregate ? "all" : makerspace.id, startDate, endDate], `${base}${query.size ? `?${query}` : ""}`, enabled);
  if (!canManageMachines) return null;
  if (!enabled) return <Panel title="Machine service"><p className="text-sm text-muted">Module disabled</p></Panel>;
  const hasRows = Boolean(report.data?.status_totals.length || report.data?.machines.length || report.data?.consumption.length);
  const groups = aggregate ? groupsFor(report.data) : [];
  return (
    <Panel title="Machine service">
      <DataState loading={report.isLoading} error={report.error} empty={!hasRows}>
        {aggregate ? <div className="mt-4 space-y-6">{groups.map((group) => (
          <section key={group.id} className="rounded-md border border-line p-4">
            <h4 className="eyebrow">{makerspaceName(group.id)}</h4>
            <MachineServiceReport report={group.report} />
          </section>
        ))}</div> : <MachineServiceReport report={report.data!} />}
      </DataState>
    </Panel>
  );
}

function MachineServiceReport({ report }: { report: Report }) {
  const status = report.status_totals[0];
  const machines = report.machines;
  const consumption = report.consumption;
  const failures = report.failure_summary;
  return <>
    {status ? <StatCards stats={[["Submitted", status.submitted], ["Completed", status.completed + status.collected], ["Failed", status.failed], ["In progress", status.in_progress]]} /> : null}
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <div><h5 className="title-section">Recorded service hours</h5><div className="mt-2"><BarChart rows={machines.slice(0, 10).map((row) => ({ label: row.machine_name, value: row.total_recorded_service_hours }))} valueLabel="hours" /></div></div>
      <div><h5 className="title-section">Failures</h5><div className="mt-2"><BarChart rows={failures.slice(0, 10).map((row) => ({ label: row.machine_name, value: row.failed_count }))} valueLabel="requests" /></div></div>
    </div>
    <ReportTable data={table(machines)} />
    {consumption.length ? <><h5 className="title-section mt-5">Consumables</h5><ReportTable data={table(consumption)} /></> : null}
  </>;
}

function groupsFor(report?: Report) {
  if (!report) return [];
  const ids = new Set<number>();
  for (const rows of [report.status_totals, report.machines, report.consumption, report.failure_summary]) for (const row of rows) if (row.makerspace_id !== undefined) ids.add(row.makerspace_id);
  return [...ids].sort((a, b) => a - b).map((id) => ({ id, report: {
    status_totals: report.status_totals.filter((row) => row.makerspace_id === id),
    machines: report.machines.filter((row) => row.makerspace_id === id),
    consumption: report.consumption.filter((row) => row.makerspace_id === id),
    failure_summary: report.failure_summary.filter((row) => row.makerspace_id === id),
  }}));
}

function table<T extends object>(rows: T[]) {
  if (!rows.length) return { rows: [], typed_rows: [] };
  return { rows: [Object.keys(rows[0] as object), ...rows.map((row) => Object.values(row as object))], typed_rows: rows };
}
