import { useStaffGet } from "./shared";
import type { ReportCell } from "./OperationsReportsParts";

export type ReportResponse<T> = { rows: ReportCell[][]; typed_rows: T[] };
export type FablabReportKey = "machine-usage" | "event-attendance" | "booking-utilization" | "maintenance-activity" | "fablab-health";
export type FablabPanelProps = {
  makerspaceId: number;
  aggregate: boolean;
  enabled: boolean;
  startDate: string;
  endDate: string;
  makerspaceName: (id: number) => string;
};
export type ScopedRow = { makerspace_id?: number };
export type MakerspaceReportGroup<T> = {
  makerspaceId: number;
  rows: T[];
  data: ReportResponse<T>;
};
export type MachineUsageRow = ScopedRow & { machine_id: number; machine_name: string; machine_type: string; is_active: boolean; usage_entries: number; usage_hours: string };
export type EventAttendanceRow = ScopedRow & { event_id: number; title: string; starts_at: string; status: string; capacity: number; registrations: number; confirmed: number; pending_approval: number; registered: number; waitlisted: number; rejected: number; cancelled: number; attended: number; attendance_rate_percent: number | null };
export type BookingUtilizationRow = ScopedRow & { space_id: number; space_name: string; kind: string; is_active: boolean; booked: number; completed: number; no_show: number; cancelled: number; upcoming: number; reserved_hours: string; completed_hours: string; window_hours: string | null; reservation_utilization_percent: number | null; no_show_rate_percent: number | null };
export type MaintenanceActivityRow = ScopedRow & { machine_id: number; machine_name: string; machine_type: string; is_active: boolean; log_count: number; costed_log_count: number; total_cost: string; average_cost: string | null; last_performed_at: string | null; average_interval_days: number | null; active_schedules: number; overdue_schedules: number };
export type FabLabHealthRow = ScopedRow & {
  events_enabled: boolean; events_available: boolean; events_in_period: number | null; events_registrations: number | null; events_attended: number | null; events_completed_attendance_rate_percent: number | null;
  bookings_enabled: boolean; bookings_available: boolean; bookings_active_spaces: number | null; bookings_non_cancelled: number | null; bookings_reserved_hours: string | null; bookings_upcoming: number | null; bookings_no_shows: number | null; bookings_reservation_utilization_percent: number | null;
  machines_enabled: boolean; machines_available: boolean; machines_active: number | null; machines_usage_hours: string | null;
  maintenance_enabled: boolean; maintenance_available: boolean; maintenance_logs: number | null; maintenance_total_cost: string | null; maintenance_overdue_schedules: number | null;
};

export function useFablabReport<T>(key: FablabReportKey, props: FablabPanelProps, limit = 100) {
  const scope = props.aggregate ? "all" : props.makerspaceId;
  const base = props.aggregate ? "/admin/analytics" : `/admin/makerspace/${props.makerspaceId}/analytics`;
  const query = new URLSearchParams({ limit: String(limit) });
  if (props.startDate) query.set("start", props.startDate);
  if (props.endDate) query.set("end", props.endDate);
  return useStaffGet<ReportResponse<T>>(
    ["fablab-report", key, scope, props.startDate, props.endDate, limit],
    `${base}/${key}?${query.toString()}`,
    props.enabled,
  );
}

export function sum(rows: object[], key: string) {
  return rows.reduce((total, row) => total + Number((row as Record<string, unknown>)[key] ?? 0), 0);
}

export function groupReportByMakerspace<T extends ScopedRow>(data?: ReportResponse<T>): MakerspaceReportGroup<T>[] {
  if (!data?.rows.length) return [];
  const [header, ...tableRows] = data.rows;
  const makerspaceIndex = header.indexOf("makerspace_id");
  if (makerspaceIndex === -1) return [];

  const groups = new Map<number, MakerspaceReportGroup<T>>();
  const groupFor = (makerspaceId: number) => {
    let group = groups.get(makerspaceId);
    if (!group) {
      group = {
        makerspaceId,
        rows: [],
        data: {
          rows: [header.filter((_, index) => index !== makerspaceIndex)],
          typed_rows: [],
        },
      };
      groups.set(makerspaceId, group);
    }
    return group;
  };

  for (const row of data.typed_rows) {
    if (row.makerspace_id !== undefined) {
      const group = groupFor(row.makerspace_id);
      group.rows.push(row);
      group.data.typed_rows.push(row);
    }
  }
  for (const row of tableRows) {
    const makerspaceId = Number(row[makerspaceIndex]);
    if (Number.isFinite(makerspaceId)) {
      groupFor(makerspaceId).data.rows.push(
        row.filter((_, index) => index !== makerspaceIndex),
      );
    }
  }
  return [...groups.values()];
}
