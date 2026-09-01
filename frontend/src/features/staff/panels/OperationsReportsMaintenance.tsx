import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { Panel } from "./shared";
import { groupReportByMakerspace, sum, useFablabReport, type FablabPanelProps, type MaintenanceActivityRow, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsMaintenance(props: FablabPanelProps) {
  const query = useFablabReport<MaintenanceActivityRow>("maintenance-activity", props);
  if (!props.enabled) return <Panel title="Maintenance"><p className="text-sm text-muted">Module disabled</p></Panel>;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <Panel title="Maintenance activity">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <>
          <p className="mt-3 text-xs text-muted">Recorded costs remain per makerspace and are never combined across makerspaces.</p>
          <div className="mt-4 space-y-6">{groups.map((group) => (
            <section key={group.makerspaceId} className="rounded-md border border-line p-4">
              <h4 className="eyebrow">{props.makerspaceName(group.makerspaceId)}</h4>
              <MaintenanceReport rows={group.rows} data={group.data} />
            </section>
          ))}</div>
        </> : <MaintenanceReport rows={rows} data={query.data} />}
      </DataState>
    </Panel>
  );
}

function MaintenanceReport({ rows, data }: { rows: MaintenanceActivityRow[]; data?: ReportResponse<MaintenanceActivityRow> }) {
  return <>
    <StatCards stats={[["Logs", sum(rows, "log_count")], ["Recorded cost", sum(rows, "total_cost")], ["Overdue schedules (snapshot)", sum(rows, "overdue_schedules")], ["Active schedules (snapshot)", sum(rows, "active_schedules")]]} />
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <BarChart rows={rows.map((row) => ({ label: row.machine_name, value: row.log_count }))} valueLabel="logs" />
      <BarChart rows={rows.map((row) => ({ label: row.machine_name, value: Number(row.total_cost) }))} valueLabel="recorded cost" />
    </div>
    <ReportTable data={data} />
  </>;
}
