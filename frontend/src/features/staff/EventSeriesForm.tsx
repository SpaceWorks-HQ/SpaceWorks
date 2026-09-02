import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { EventSeries, EventSeriesPayload } from "./eventSeriesApi";

export type SeriesFormValues = EventSeriesPayload & {
  frequency: "DAILY" | "WEEKLY" | "MONTHLY";
  interval: number;
  byday: string;
};

const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export const emptySeriesForm: SeriesFormValues = {
  title: "", description: "", location: "", location_kind: "other", custom_form: null,
  capacity: 0, payment_amount: "0.00", registration_requires_approval: false,
  registration_cutoff_lead_minutes: null, is_public: false,
  recurrence_timezone: zone, dtstart_local_date: "", dtstart_local_time: "",
  recurrence_rule: "FREQ=WEEKLY;INTERVAL=1", duration_minutes: 60,
  frequency: "WEEKLY", interval: 1, byday: "",
};

export function valuesForSeries(series: EventSeries): SeriesFormValues {
  const parts = Object.fromEntries(series.recurrence_rule.split(";").map((part) => part.split("=", 2)));
  return {
    ...series,
    frequency: (parts.FREQ as SeriesFormValues["frequency"]) || "WEEKLY",
    interval: Number(parts.INTERVAL || 1),
    byday: parts.BYDAY || "",
  };
}

export function seriesPayload(values: SeriesFormValues): EventSeriesPayload {
  const rule = [`FREQ=${values.frequency}`, `INTERVAL=${Math.max(1, values.interval)}`];
  if (values.frequency === "WEEKLY" && values.byday.trim()) rule.push(`BYDAY=${values.byday.trim().toUpperCase()}`);
  const { frequency: _frequency, interval: _interval, byday: _byday, ...payload } = values;
  return { ...payload, recurrence_rule: rule.join(";"), title: payload.title.trim(), location: payload.location.trim() };
}

export function EventSeriesFields({ values, setValues, disabled = false }: {
  values: SeriesFormValues; setValues: (values: SeriesFormValues) => void; disabled?: boolean;
}) {
  const set = <K extends keyof SeriesFormValues>(key: K, value: SeriesFormValues[K]) => setValues({ ...values, [key]: value });
  const unit = { DAILY: "day", WEEKLY: "week", MONTHLY: "month" }[values.frequency];
  const cadence = `Every ${values.interval > 1 ? values.interval + " " : ""}${unit}${values.interval > 1 ? "s" : ""} at ${values.dtstart_local_time || "the selected time"} (${values.recurrence_timezone}).`;
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Series title<input className="desk-input" required maxLength={200} disabled={disabled} value={values.title} onChange={(e) => set("title", e.target.value)} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">First local date<input className="desk-input" type="date" required disabled={disabled} value={values.dtstart_local_date} onChange={(e) => set("dtstart_local_date", e.target.value)} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Local start time<input className="desk-input" type="time" required disabled={disabled} value={values.dtstart_local_time} onChange={(e) => set("dtstart_local_time", e.target.value)} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">IANA timezone<input className="desk-input" required disabled={disabled} value={values.recurrence_timezone} onChange={(e) => set("recurrence_timezone", e.target.value)} /><span className="text-xs font-normal text-muted">Wall-clock time stays fixed across daylight-saving changes.</span></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Duration (minutes)<input className="desk-input" type="number" min="1" required disabled={disabled} value={values.duration_minutes} onChange={(e) => set("duration_minutes", Number(e.target.value))} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Repeats<select className="desk-input" disabled={disabled} value={values.frequency} onChange={(e) => set("frequency", e.target.value as SeriesFormValues["frequency"])}><option value="DAILY">Daily</option><option value="WEEKLY">Weekly</option><option value="MONTHLY">Monthly</option></select></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Every<input className="desk-input" type="number" min="1" disabled={disabled} value={values.interval} onChange={(e) => set("interval", Number(e.target.value))} /></label>
    {values.frequency === "WEEKLY" ? <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Weekdays (optional)<input className="desk-input" disabled={disabled} placeholder="MO,WE,FR" value={values.byday} onChange={(e) => set("byday", e.target.value)} /></label> : null}
    <p className="rounded-lg border border-line bg-surface p-3 text-sm text-muted sm:col-span-2">{cadence}</p>
    <label className="grid gap-1 text-sm font-semibold text-ink">Location<input className="desk-input" maxLength={255} disabled={disabled} value={values.location} onChange={(e) => set("location", e.target.value)} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Capacity per occurrence<input className="desk-input" type="number" min="0" disabled={disabled} value={values.capacity} onChange={(e) => set("capacity", Number(e.target.value))} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Price per occurrence<input className="desk-input" type="number" min="0" step="0.01" disabled={disabled} value={values.payment_amount} onChange={(e) => set("payment_amount", e.target.value)} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Registration closes minutes before<input className="desk-input" type="number" min="0" disabled={disabled} value={values.registration_cutoff_lead_minutes ?? ""} onChange={(e) => set("registration_cutoff_lead_minutes", e.target.value === "" ? null : Number(e.target.value))} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Description<textarea className="desk-input min-h-24" disabled={disabled} value={values.description} onChange={(e) => set("description", e.target.value)} /></label>
    <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" disabled={disabled} checked={values.registration_requires_approval} onChange={(e) => set("registration_requires_approval", e.target.checked)} />Require approval</label>
    <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" disabled={disabled} checked={values.is_public} onChange={(e) => set("is_public", e.target.checked)} />Public occurrences</label>
    <div className="sm:col-span-2"><CustomFormBuilder value={values.custom_form} onChange={(value) => set("custom_form", value)} disabled={disabled} /></div>
  </div>;
}
