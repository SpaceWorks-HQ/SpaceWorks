import { StructuredApiError, staffRequest } from "../../../lib/api";
import type { NotificationDestination } from "../notificationDestinationTypes";

// Hand-written mirrors of `apps/operations/serializers_report_schedules.py`; replace with
// the generated types once the OpenAPI snapshot is regenerated.
export type ReportDelivery = {
  id: number;
  status: string;
  error: string;
  created_at: string;
  expires_at: string | null;
  download_url: string | null;
};

export type ReportSchedule = {
  id: number;
  makerspace: number;
  report_key: string;
  filters: { window_days?: number; start?: string; end?: string; status?: string; subject_type?: string };
  grain: string;
  format: "csv" | "xlsx";
  cadence: "daily" | "weekly" | "monthly";
  next_run_at: string;
  last_run_at: string | null;
  is_active: boolean;
  destination: number | null;
  recipient_emails: string[];
  created_by: number | null;
  created_at: string;
  updated_at: string;
  last_delivery: ReportDelivery | null;
};

export type ReportScheduleInput = {
  report_key: string;
  grain: string;
  format: ReportSchedule["format"];
  cadence: ReportSchedule["cadence"];
  destination: number | null;
  recipient_emails: string[];
  filters: ReportSchedule["filters"];
};

export const CADENCES: [ReportSchedule["cadence"], string][] = [
  ["daily", "Daily"],
  ["weekly", "Weekly"],
  ["monthly", "Monthly"],
];

export const MAX_RECIPIENT_EMAILS = 10;

export const reportScheduleKeys = {
  list: (makerspaceId: number) => ["report-schedules", makerspaceId] as const,
  destinations: (makerspaceId: number) => ["notification-destinations", makerspaceId] as const,
};

export function listSchedules(makerspaceId: number) {
  return staffRequest<ReportSchedule[]>(`/admin/makerspaces/${makerspaceId}/report-schedules`);
}

export function createSchedule(makerspaceId: number, input: ReportScheduleInput) {
  return staffRequest<ReportSchedule>(`/admin/makerspaces/${makerspaceId}/report-schedules`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateSchedule(id: number, input: Partial<ReportScheduleInput> & { is_active?: boolean }) {
  return staffRequest<ReportSchedule>(`/admin/report-schedules/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteSchedule(id: number) {
  return staffRequest<void>(`/admin/report-schedules/${id}`, { method: "DELETE" });
}

export function runScheduleNow(id: number) {
  return staffRequest<ReportDelivery>(`/admin/report-schedules/${id}/run-now`, { method: "POST" });
}

/** Chat rooms only: the serializer rejects any destination outside the chat channels. */
export function listChatDestinations(makerspaceId: number) {
  return staffRequest<NotificationDestination[]>(`/admin/makerspace/${makerspaceId}/notification-destinations`);
}

/** Split a pasted list on commas, whitespace or newlines; blanks and duplicates drop out. */
export function parseRecipientEmails(raw: string) {
  return [...new Set(raw.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean))];
}

export function scheduleErrorText(error: unknown, fallback: string) {
  if (error instanceof StructuredApiError) {
    if (error.code === "report_schedule_skipped") return "The schedule is inactive or was skipped, so nothing was generated.";
    return error.message || fallback;
  }
  return error instanceof Error ? error.message : fallback;
}
