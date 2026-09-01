import type { EventPayload, StaffEvent } from "./eventsApi";

export type EventFormValues = Omit<EventPayload, "starts_at" | "ends_at" | "registration_cutoff_at"> & {
  starts_at: string;
  ends_at: string;
  registration_cutoff_at: string | null;
};

export const emptyEventForm: EventFormValues = {
  title: "", description: "", starts_at: "", ends_at: "", location: "",
  capacity: 0, payment_amount: "0.00", registration_requires_approval: false,
  registration_cutoff_at: null, registration_cutoff_lead_minutes: null,
  is_public: false,
};

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function valuesFor(event: StaffEvent): EventFormValues {
  return {
    title: event.title, description: event.description,
    starts_at: localDate(event.starts_at), ends_at: localDate(event.ends_at),
    location: event.location, capacity: event.capacity,
    payment_amount: event.payment_amount,
    registration_requires_approval: event.registration_requires_approval,
    registration_cutoff_at: event.registration_cutoff_at ? localDate(event.registration_cutoff_at) : null,
    registration_cutoff_lead_minutes: event.registration_cutoff_lead_minutes,
    is_public: event.is_public,
  };
}

export function payloadFor(values: EventFormValues): EventPayload {
  return {
    ...values, title: values.title.trim(), description: values.description.trim(),
    location: values.location.trim(), starts_at: new Date(values.starts_at).toISOString(),
    ends_at: new Date(values.ends_at).toISOString(),
    registration_cutoff_at: values.registration_cutoff_at ? new Date(values.registration_cutoff_at).toISOString() : null,
  };
}

export function EventFields({ values, setValues, disabled = false, approvalLocked = false }: {
  values: EventFormValues; setValues: (values: EventFormValues) => void;
  disabled?: boolean; approvalLocked?: boolean;
}) {
  const set = <K extends keyof EventFormValues>(key: K, value: EventFormValues[K]) => setValues({ ...values, [key]: value });
  const cutoffMode = values.registration_cutoff_at !== null ? "absolute" : values.registration_cutoff_lead_minutes !== null ? "lead" : "none";
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Title<input className="desk-input" value={values.title} onChange={(e) => set("title", e.target.value)} required disabled={disabled} maxLength={200} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Starts<input className="desk-input" type="datetime-local" value={values.starts_at} onChange={(e) => set("starts_at", e.target.value)} required disabled={disabled} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Ends<input className="desk-input" type="datetime-local" value={values.ends_at} onChange={(e) => set("ends_at", e.target.value)} required disabled={disabled} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Location<input className="desk-input" value={values.location} onChange={(e) => set("location", e.target.value)} disabled={disabled} maxLength={255} /></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Capacity<input className="desk-input" type="number" min="0" value={values.capacity} onChange={(e) => set("capacity", Number(e.target.value))} disabled={disabled} /><span className="text-xs font-normal text-muted">Use 0 for Unlimited.</span></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Registration price<input className="desk-input" type="number" min="0" step="0.01" value={values.payment_amount} onChange={(e) => set("payment_amount", e.target.value)} disabled={disabled} /><span className="text-xs font-normal text-muted">Charged only when a place is confirmed.</span></label>
    <label className="grid gap-1 text-sm font-semibold text-ink">Registration cutoff<select className="desk-input" value={cutoffMode} disabled={disabled} onChange={(e) => { const mode = e.target.value; setValues({ ...values, registration_cutoff_at: mode === "absolute" ? (values.starts_at || "") : null, registration_cutoff_lead_minutes: mode === "lead" ? 0 : null }); }}><option value="none">No cutoff</option><option value="absolute">At a date and time</option><option value="lead">Before the event starts</option></select></label>
    {cutoffMode === "absolute" ? <label className="grid gap-1 text-sm font-semibold text-ink">Cutoff time<input className="desk-input" type="datetime-local" value={values.registration_cutoff_at ?? ""} onChange={(e) => set("registration_cutoff_at", e.target.value)} disabled={disabled} required /></label> : null}
    {cutoffMode === "lead" ? <label className="grid gap-1 text-sm font-semibold text-ink">Minutes before start<input className="desk-input" type="number" min="0" value={values.registration_cutoff_lead_minutes ?? 0} onChange={(e) => set("registration_cutoff_lead_minutes", Number(e.target.value))} disabled={disabled} /></label> : null}
    <label className="grid gap-1 text-sm font-semibold text-ink sm:col-span-2">Description<textarea className="desk-input min-h-24" value={values.description} onChange={(e) => set("description", e.target.value)} disabled={disabled} /></label>
    <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2"><input type="checkbox" checked={values.registration_requires_approval} onChange={(e) => set("registration_requires_approval", e.target.checked)} disabled={disabled || approvalLocked} />Require staff approval for registrations</label>
    <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2"><input type="checkbox" checked={values.is_public} onChange={(e) => set("is_public", e.target.checked)} disabled={disabled} />Show this event on the public Events page</label>
  </div>;
}
