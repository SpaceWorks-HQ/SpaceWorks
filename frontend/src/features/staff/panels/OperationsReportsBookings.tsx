import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { Panel } from "./shared";
import { groupReportByMakerspace, sum, useFablabReport, type BookingUtilizationRow, type FablabPanelProps, type ReportResponse } from "./operationsReportsFablabApi";

export function OperationsReportsBookings(props: FablabPanelProps) {
  const query = useFablabReport<BookingUtilizationRow>("booking-utilization", props);
  if (!props.enabled) return <Panel title="Bookings"><p className="text-sm text-muted">Module disabled</p></Panel>;
  const rows = query.data?.typed_rows ?? [];
  const groups = groupReportByMakerspace(query.data);
  return (
    <Panel title="Bookable Space utilization">
      <p className="text-xs text-muted">Utilization requires both date bounds and measures calendar reservation occupancy, not physical presence.</p>
      <DataState loading={query.isLoading} error={query.error} empty={!rows.length}>
        {props.aggregate ? <div className="mt-4 space-y-6">{groups.map((group) => (
          <section key={group.makerspaceId} className="rounded-md border border-line p-4">
            <h4 className="eyebrow">{props.makerspaceName(group.makerspaceId)}</h4>
            <BookingsReport rows={group.rows} data={group.data} />
          </section>
        ))}</div> : <BookingsReport rows={rows} data={query.data} />}
      </DataState>
    </Panel>
  );
}

function BookingsReport({ rows, data }: { rows: BookingUtilizationRow[]; data?: ReportResponse<BookingUtilizationRow> }) {
  return <>
    <StatCards stats={[["Reserved hours", sum(rows, "reserved_hours")], ["Completed hours", sum(rows, "completed_hours")], ["Upcoming", sum(rows, "upcoming")], ["No-shows", sum(rows, "no_show")]]} />
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <BarChart rows={rows.filter((row) => row.reservation_utilization_percent !== null).map((row) => ({ label: row.space_name, value: row.reservation_utilization_percent ?? 0 }))} valueLabel="% reserved" />
      <BarChart rows={rows.filter((row) => row.no_show_rate_percent !== null).map((row) => ({ label: row.space_name, value: row.no_show_rate_percent ?? 0 }))} valueLabel="% no-show" />
    </div>
    <ReportTable data={data} />
  </>;
}
