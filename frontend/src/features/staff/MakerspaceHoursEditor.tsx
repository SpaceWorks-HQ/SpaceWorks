import { dayLabels, weekdays, type HoursDraft, type Interval } from "./makerspaceProfileForm";

function IntervalsEditor({ label, intervals, onChange }: {
  label: string; intervals: Interval[]; onChange: (intervals: Interval[]) => void;
}) {
  return <div className="grid gap-2">
    {intervals.length === 0 ? <span className="text-sm text-muted">Closed</span> : null}
    {intervals.map((interval, index) => <div className="flex flex-wrap gap-2" key={index}>
      {(["start", "end"] as const).map(field => <label className="grid gap-1 text-sm" key={field}>
        <span>{label} {field} {index + 1}</span>
        <input className="desk-input w-28" value={interval[field]} placeholder="HH:MM" maxLength={5}
          onChange={event => onChange(intervals.map((row, i) => i === index ? { ...row, [field]: event.target.value } : row))} />
      </label>)}
      <button className="desk-button self-end" type="button" aria-label={`Remove ${label} interval ${index + 1}`}
        onClick={() => onChange(intervals.filter((_, i) => i !== index))}>Remove</button>
    </div>)}
    <button className="desk-button w-fit" type="button" disabled={intervals.length >= 24}
      onClick={() => onChange([...intervals, { start: "09:00", end: "17:00" }])}>Add {label} interval</button>
  </div>;
}

export function MakerspaceHoursEditor({ value, onChange }: { value: HoursDraft; onChange: (value: HoursDraft) => void }) {
  return <div className="grid gap-4">
    <label className="flex gap-2 text-sm font-semibold">
      <input type="checkbox" checked={value.configured} onChange={event => onChange({ ...value, configured: event.target.checked })} />
      Set weekly opening hours
    </label>
    <p className="text-sm text-muted">Without weekly hours the space is always open, except on dated exceptions. Empty days are closed. Use local HH:MM; midnight at the end of a day is 24:00. Split overnight hours across days.</p>
    {value.configured ? weekdays.map((day, index) => <fieldset className="rounded border border-line p-3" key={day}>
      <legend className="px-1 font-semibold">{dayLabels[index]}</legend>
      <IntervalsEditor label={dayLabels[index]} intervals={value.weekly[day]}
        onChange={intervals => onChange({ ...value, weekly: { ...value.weekly, [day]: intervals } })} />
    </fieldset>) : null}
    <h4 className="font-semibold">Dated exceptions and holidays</h4>
    <p className="text-sm text-muted">An exception replaces that date&apos;s regular hours. Leave it empty for a holiday closure.</p>
    {value.exceptions.map((row, index) => {
      const update = (patch: Partial<typeof row>) => onChange({ ...value, exceptions: value.exceptions.map((item, i) => i === index ? { ...item, ...patch } : item) });
      return <fieldset className="grid gap-3 rounded border border-line p-3" key={index}>
        <legend className="px-1 font-semibold">Exception {index + 1}</legend>
        <label className="grid gap-1 text-sm">Exception date {index + 1}
          <input className="desk-input" type="date" value={row.date} onChange={event => update({ date: event.target.value })} />
        </label>
        <IntervalsEditor label={`Exception ${index + 1}`} intervals={row.intervals} onChange={intervals => update({ intervals })} />
        <button className="desk-button w-fit" type="button" onClick={() => onChange({ ...value, exceptions: value.exceptions.filter((_, i) => i !== index) })}>Remove exception {index + 1}</button>
      </fieldset>;
    })}
    <button className="desk-button w-fit" type="button" disabled={value.exceptions.length >= 366}
      onClick={() => onChange({ ...value, exceptions: [...value.exceptions, { date: "", intervals: [] }] })}>Add exception</button>
  </div>;
}
