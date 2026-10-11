import type { ScheduleInput } from "./maintenanceApi";

export function MaintenanceMeterFields({ value, change }: { value: ScheduleInput; change: (value: ScheduleInput) => void }) {
  return <>
    <label className="grid gap-1 text-sm">Trigger<select className="desk-input" value={value.trigger ?? "days"} onChange={event => change({ ...value, trigger: event.target.value as ScheduleInput["trigger"] })}><option value="days">Calendar</option><option value="usage">Usage</option><option value="both">Calendar or usage</option></select></label>
    {value.trigger && value.trigger !== "days" ? <>
      <label className="grid gap-1 text-sm">Usage hours<input className="desk-input" type="number" min={0.01} step="0.01" value={value.usage_hours ?? ""} onChange={event => change({ ...value, usage_hours: event.target.value || null })} /></label>
      <label className="grid gap-1 text-sm">Job count<input className="desk-input" type="number" min={1} step={1} value={value.job_count ?? ""} onChange={event => change({ ...value, job_count: event.target.value ? Number(event.target.value) : null })} /></label>
    </> : null}
  </>;
}
