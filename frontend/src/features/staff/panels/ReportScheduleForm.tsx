import { useState } from "react";

import { Field } from "../../../components/ui";
import type { NotificationDestination } from "../notificationDestinationTypes";
import type { ReportCatalogItem } from "./operationsReportsConfig";
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
  };
}

/** Mirrors `ReportScheduleSerializer.validate`: a chat destination or at least one email. */
export function validateScheduleForm(form: ScheduleFormValues): string | null {
  if (!form.report_key) return "Choose a report.";
  const emails = parseRecipientEmails(form.recipients);
  if (!form.destination && !emails.length) return "Choose a chat destination or add at least one email address.";
  if (emails.length > MAX_RECIPIENT_EMAILS) return `At most ${MAX_RECIPIENT_EMAILS} recipient emails are allowed.`;
  if (emails.some((email) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))) return "One of the recipient emails is not valid.";
  if (form.window_days.trim() && !/^\d+$/.test(form.window_days.trim())) return "Window days must be a whole number.";
  return null;
}

export function formToInput(form: ScheduleFormValues): ReportScheduleInput {
  const windowDays = form.window_days.trim();
  return {
    report_key: form.report_key,
    grain: form.grain,
    format: form.format,
    cadence: form.cadence,
    destination: form.destination ? Number(form.destination) : null,
    recipient_emails: parseRecipientEmails(form.recipients),
    filters: windowDays ? { window_days: Number(windowDays) } : {},
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
  const grains = reports.find((report) => report.key === form.report_key)?.grains ?? ["day"];
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
            const allowed = reports.find((report) => report.key === key)?.grains ?? ["day"];
            setForm((current) => ({ ...current, report_key: key, grain: allowed.includes(current.grain) ? current.grain : allowed[0] }));
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
          <option value="csv">CSV</option><option value="xlsx">XLSX</option>
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
      <Field label="Recipient emails" hint={`Comma or newline separated, up to ${MAX_RECIPIENT_EMAILS}.`} className="sm:col-span-3">
        <textarea className="desk-input min-h-16" value={form.recipients} onChange={(event) => set("recipients", event.target.value)} />
      </Field>
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
