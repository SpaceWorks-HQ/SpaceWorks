import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { Panel } from "./shared";
import { groupReportByMakerspace, sum, useFablabReport, type FablabPanelProps, type MachineUsageRow, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsMachineUsage(props: FablabPanelProps) {
  const query = useFablabReport<MachineUsageRow>("machine-usage", props);
  if (!props.enabled) return <Panel title="Machine usage"><p className="text-sm text-muted">Module disabled</p></Panel>;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <Panel title="Machine usage">
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <div className="mt-4 space-y-6">{groups.map((group) => (
          <section key={group.makerspaceId} className="rounded-md border border-line p-4">
            <h4 className="eyebrow">{props.makerspaceName(group.makerspaceId)}</h4>
            <MachineUsageReport rows={group.rows} data={group.data} />
          </section>
        ))}</div> : <MachineUsageReport rows={rows} data={query.data} />}
      </DataState>
    </Panel>
  );
}

function MachineUsageReport({ rows, data }: { rows: MachineUsageRow[]; data?: ReportResponse<MachineUsageRow> }) {
  return <>
    <StatCards stats={[["Usage hours", sum(rows, "usage_hours")], ["Usage entries", sum(rows, "usage_entries")], ["Machines", rows.length], ["Active", rows.filter((row) => row.is_active).length]]} />
    <div className="mt-4"><BarChart rows={rows.slice(0, 10).map((row) => ({ label: row.machine_name, value: Number(row.usage_hours) }))} valueLabel="hours" /></div>
    <ReportTable data={data} />
  </>;
}
