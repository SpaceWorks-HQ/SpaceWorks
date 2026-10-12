import { useState } from "react";

import { Field } from "../../../components/ui";
import type { NotificationDestination } from "../notificationDestinationTypes";
import { reportFormats, type ReportCatalogItem } from "./operationsReportsConfig";
import {
  CADENCES,
  MAX_RECIPIENT_EMAILS,
  parseRecipientEmails,
  type ReportSchedule,
  type ReportScheduleInput,
} from "./reportSchedulesApi";

export type ScheduleFormValues = {
  report_key: string;
  grain: string;
  format: ReportSchedule["format"];
  cadence: ReportSchedule["cadence"];
  destination: string;
  recipients: string;
  window_days: string;
  role_slugs?: string;
  actions?: string;
  non_empty?: boolean;
  metric?: string;
  comparison?: string;
  threshold?: string;
  currency?: string;
  pinned_filters?: ReportSchedule["filters"];
};

export function emptyScheduleForm(reports: ReportCatalogItem[]): ScheduleFormValues {
  return {
    report_key: reports[0]?.key ?? "",
    grain: reports[0]?.grains?.[0] ?? "day",
    format: "csv",
    cadence: "weekly",
    destination: "",
    recipients: "",
    window_days: "7",
    role_slugs: "", actions: "", non_empty: false, metric: "", comparison: "gt", threshold: "0", currency: "",
  };
}

export function scheduleToForm(schedule: ReportSchedule): ScheduleFormValues {
  return {
    report_key: schedule.report_key,
    grain: schedule.grain,
    format: schedule.format,
    cadence: schedule.cadence,
    destination: schedule.destination == null ? "" : String(schedule.destination),
    recipients: schedule.recipient_emails.join(", "),
    window_days: schedule.filters?.window_days == null ? "" : String(schedule.filters.window_days),
    role_slugs: (schedule.recipient_roles ?? []).join(", "), actions: (schedule.recipient_actions ?? []).join(", "),
    non_empty: schedule.condition?.non_empty ?? false, metric: schedule.condition?.metric ?? "",
    comparison: schedule.condition?.operator ?? "gt", threshold: schedule.condition?.value ?? "0",
    currency: schedule.condition?.currency ?? "",
    pinned_filters: schedule.filters,
  };
}

/** A schedule needs a destination, an external email, or a live staff selector. */
export function validateScheduleForm(form: ScheduleFormValues): string | null {
  if (!form.report_key) return "Choose a report.";
  const emails = parseRecipientEmails(form.recipients);
  if (!form.destination && !emails.length && !form.role_slugs?.trim() && !form.actions?.trim()) return "Choose a chat destination or add at least one email address.";
  if (emails.length > MAX_RECIPIENT_EMAILS) return `At most ${MAX_RECIPIENT_EMAILS} recipient emails are allowed.`;
  if (emails.some((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))) return "One of the recipient emails is not valid.";
  if (form.window_days.trim() && !/^\d+$/.test(form.window_days.trim())) return "Window days must be a whole number.";
  if (form.metric && (!form.threshold?.trim() || !Number.isFinite(Number(form.threshold)))) return "Enter a numeric threshold.";
  if (form.currency && !/^[a-z]{3}$/.test(form.currency)) return "Currency must be three lowercase letters.";
  return null;
}

export function formToInput(form: ScheduleFormValues): ReportScheduleInput {
  const windowDays = form.window_days.trim();
  const { window_days: _oldWindow, start, end, ...otherFilters } = form.pinned_filters ?? {};
  return {
    report_key: form.report_key,
    grain: form.grain,
    format: form.format,
    cadence: form.cadence,
    destination: form.destination ? Number(form.destination) : null,
    recipient_emails: parseRecipientEmails(form.recipients),
    filters: windowDays ? { ...otherFilters, window_days: Number(windowDays) } : { ...otherFilters, ...(start ? { start } : {}), ...(end ? { end } : {}) },
    recipient_roles: parseRecipientEmails(form.role_slugs ?? ""),
    recipient_actions: parseRecipientEmails(form.actions ?? ""),
    condition: {
      ...(form.non_empty ? { non_empty: true } : {}),
      ...(form.metric ? { metric: form.metric, operator: form.comparison ?? "gt", value: form.threshold ?? "0",
        ...(form.currency ? { currency: form.currency } : {}) } : {}),
    },
  };
}

export function ReportScheduleForm({
  reports,
  destinations,
  initial,
  editing,
  pending,
  onSubmit,
  onCancel,
}: {
  reports: ReportCatalogItem[];
  destinations: NotificationDestination[];
  initial: ScheduleFormValues;
  editing: boolean;
  pending: boolean;
  onSubmit: (input: ReportScheduleInput) => void;
  onCancel?: () => void;
}) {
  const [form, setForm] = useState(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const selected = reports.find((report) => report.key === form.report_key);
  const grains = selected?.grains ?? ["day"];
  const formats = selected ? reportFormats(selected) : (["csv", "xlsx"] as const);
  const set = <K extends keyof ScheduleFormValues>(key: K, value: ScheduleFormValues[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setProblem(null);
  };

  return (
    <form
      className="grid gap-2 sm:grid-cols-3"
      aria-label={editing ? "Edit report schedule" : "New report schedule"}
      onSubmit={(event) => {
        event.preventDefault();
        const next = validateScheduleForm(form);
        setProblem(next);
        if (!next) onSubmit(formToInput(form));
      }}
    >
      <Field label="Report">
        <select
          className="desk-input"
          value={form.report_key}
          onChange={(event) => {
            const key = event.target.value;
            const next = reports.find((report) => report.key === key);
            const allowed = next?.grains ?? ["day"];
            const nextFormats = next ? reportFormats(next) : ["csv", "xlsx"];
            setForm((current) => ({
              ...current, report_key: key,
              metric: "",
              pinned_filters: current.pinned_filters ? {
                start: current.pinned_filters.start, end: current.pinned_filters.end,
              } : undefined,
              grain: allowed.includes(current.grain) ? current.grain : allowed[0],
              format: nextFormats.includes(current.format) ? current.format : (nextFormats[0] as ReportSchedule["format"]),
            }));
            setProblem(null);
          }}
        >
          {!reports.length ? <option value="">No exportable reports</option> : null}
          {reports.map((report) => <option key={report.key} value={report.key}>{report.title}</option>)}
        </select>
      </Field>
      <Field label="Grain">
        <select className="desk-input" value={form.grain} onChange={(event) => set("grain", event.target.value)}>
          {(grains.length ? grains : ["day"]).map((grain) => <option key={grain} value={grain}>{grain}</option>)}
        </select>
      </Field>
      <Field label="Format">
        <select className="desk-input" value={form.format} onChange={(event) => set("format", event.target.value as ReportSchedule["format"])}>
          {formats.map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}
        </select>
      </Field>
      <Field label="Cadence">
        <select className="desk-input" value={form.cadence} onChange={(event) => set("cadence", event.target.value as ReportSchedule["cadence"])}>
          {CADENCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </Field>
      <Field label="Chat destination" hint={destinations.length ? undefined : "No chat destinations configured; email only."}>
        <select className="desk-input" value={form.destination} onChange={(event) => set("destination", event.target.value)}>
          <option value="">Email only</option>
          {destinations.map((destination) => (
            <option key={destination.id} value={destination.id}>{destination.label} ({destination.channel})</option>
          ))}
        </select>
      </Field>
      <Field label="Window (days)" hint="How far back each run looks; blank keeps the report's default range.">
        <input className="desk-input" inputMode="numeric" value={form.window_days} onChange={(event) => set("window_days", event.target.value)} />
      </Field>
      <Field label="Recipient emails" hint={`External recipients only, up to ${MAX_RECIPIENT_EMAILS}. Use roles or actions for staff.`} className="sm:col-span-3">
        <textarea className="desk-input min-h-16" value={form.recipients} onChange={(event) => set("recipients", event.target.value)} />
      </Field>
      <Field label="Recipient role slugs" hint="Comma-separated role slugs from this makerspace's role settings. Resolved each run.">
        <input className="desk-input" value={form.role_slugs ?? ""} onChange={(event) => set("role_slugs", event.target.value)} />
      </Field>
      <Field label="Recipient actions" hint="Comma-separated action keys, such as view_finance. Recipients must also be able to open this report.">
        <input className="desk-input" value={form.actions ?? ""} onChange={(event) => set("actions", event.target.value)} />
      </Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.non_empty ?? false} onChange={(event) => set("non_empty", event.target.checked)} />Send only when non-empty</label>
      <Field label="Threshold metric" hint="Sum this column across the matching rows.">
        <select className="desk-input" value={form.metric ?? ""} onChange={(event) => set("metric", event.target.value)}>
          <option value="">No threshold</option>{(selected?.condition_metrics ?? []).map((metric) => <option key={metric}>{metric}</option>)}
        </select>
      </Field>
      <Field label="Comparison"><select className="desk-input" value={form.comparison ?? "gt"} onChange={(event) => set("comparison", event.target.value)}>
        {[["gt", ">"], ["gte", ">="], ["lt", "<"], ["lte", "<="], ["eq", "="]].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></Field>
      <Field label="Threshold"><input className="desk-input" inputMode="decimal" value={form.threshold ?? "0"} onChange={(event) => set("threshold", event.target.value)} /></Field>
      <Field label="Threshold currency" hint="Choose one currency for a money report with several currencies."><input className="desk-input" maxLength={3} value={form.currency ?? ""} onChange={(event) => set("currency", event.target.value.toLowerCase())} /></Field>
      <div className="flex items-center gap-2 sm:col-span-3">
        <button className="desk-button-primary" type="submit" disabled={pending || !reports.length}>
          {pending ? "Saving…" : editing ? "Save schedule" : "Create schedule"}
        </button>
        {onCancel ? <button className="desk-button" type="button" onClick={onCancel}>Cancel</button> : null}
      </div>
      {problem ? <p className="text-sm text-danger sm:col-span-3" role="alert">{problem}</p> : null}
    </form>
  );
}
