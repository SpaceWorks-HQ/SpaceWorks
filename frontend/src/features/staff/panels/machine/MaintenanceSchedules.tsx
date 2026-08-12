import { useState } from "react";

import { EmptyState } from "../../../../components/ui";
import {
  useCreateMaintenanceSchedule,
  useDeactivateMaintenanceSchedule,
  useUpdateMaintenanceSchedule,
  type MaintenanceSchedule,
  type ScheduleInput,
} from "./maintenanceApi";

const emptySchedule = (): ScheduleInput => ({
  description: "",
  interval_days: 30,
  next_due: new Date().toISOString().slice(0, 10),
});

export function MaintenanceSchedules({
  makerspaceId, machineId, schedules, canEdit, retired, onComplete,
}: {
  makerspaceId: number;
  machineId: number;
  schedules: MaintenanceSchedule[];
  canEdit: boolean;
  retired: boolean;
  onComplete: (schedule: MaintenanceSchedule) => void;
}) {
  const [draft, setDraft] = useState<ScheduleInput>(emptySchedule);
  const [editing, setEditing] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<ScheduleInput>(emptySchedule);
  const create = useCreateMaintenanceSchedule(makerspaceId, machineId);
  const update = useUpdateMaintenanceSchedule(makerspaceId, machineId);
  const deactivate = useDeactivateMaintenanceSchedule(makerspaceId, machineId);
  const active = schedules.filter((row) => row.is_active);
  const inactive = schedules.filter((row) => !row.is_active);

  const fields = (
    value: ScheduleInput,
    change: (value: ScheduleInput) => void,
    prefix: string,
  ) => (
    <>
      <label className="eyebrow grid gap-1">
        Description
        <input
          className="desk-input"
          aria-label={`${prefix} description`}
          value={value.description}
          onChange={(event) => change({ ...value, description: event.target.value })}
          required
        />
      </label>
      <label className="eyebrow grid gap-1">
        Interval (days)
        <input
          className="desk-input"
          type="number"
          min={1}
          value={value.interval_days}
          onChange={(event) => change({ ...value, interval_days: Number(event.target.value) })}
          required
        />
      </label>
      <label className="eyebrow grid gap-1">
        Next due
        <input
          className="desk-input"
          type="date"
          value={value.next_due}
          onChange={(event) => change({ ...value, next_due: event.target.value })}
          required
        />
      </label>
    </>
  );

  return (
    <section className="grid gap-3" aria-labelledby="maintenance-schedules-title">
      <h3 id="maintenance-schedules-title" className="title-section">
        Maintenance schedules
      </h3>
      {!schedules.length ? (
        <EmptyState
          title="No maintenance schedules"
          description="Create a recurring schedule to track upcoming maintenance."
        />
      ) : null}
      {[...active, ...inactive].map((schedule) => (
        <article key={schedule.id} className="rounded-lg border border-line bg-bg p-3">
          {editing === schedule.id ? (
            <form
              className="grid gap-2 sm:grid-cols-3"
              onSubmit={(event) => {
                event.preventDefault();
                update.mutate(
                  { id: schedule.id, input: editDraft },
                  { onSuccess: () => setEditing(null) },
                );
              }}
            >
              {fields(editDraft, setEditDraft, "Edit schedule")}
              <div className="flex gap-2 sm:col-span-3">
                <button className="desk-button-primary" type="submit" disabled={update.isPending}>
                  {update.isPending ? "Saving..." : "Save schedule"}
                </button>
                <button className="desk-button-ghost" type="button" onClick={() => setEditing(null)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap items-start gap-2">
              <div className="min-w-0 flex-1">
                <strong className="block text-sm text-ink">{schedule.description}</strong>
                <span className="text-xs text-muted">
                  Every {schedule.interval_days} days · {formatDate(schedule.next_due)}
                </span>
              </div>
              <span className={schedule.overdue
                ? "rounded-md bg-danger/15 px-2 py-1 text-xs font-semibold text-danger"
                : schedule.is_active
                  ? "rounded-md bg-accent/15 px-2 py-1 text-xs font-semibold text-ink"
                  : "rounded-md bg-surface px-2 py-1 text-xs font-semibold text-muted"}
              >
                {schedule.overdue ? "Overdue" : schedule.is_active ? "Due as scheduled" : "Inactive"}
              </span>
              {canEdit && schedule.is_active && !retired ? (
                <div className="flex gap-2">
                  <button className="desk-button-success" type="button" onClick={() => onComplete(schedule)}>
                    Complete
                  </button>
                  <button
                    className="desk-button-ghost"
                    type="button"
                    onClick={() => {
                      setEditDraft({
                        description: schedule.description,
                        interval_days: schedule.interval_days,
                        next_due: schedule.next_due,
                      });
                      setEditing(schedule.id);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    className="desk-button-danger"
                    type="button"
                    disabled={deactivate.isPending}
                    onClick={() => {
                      if (window.confirm("Deactivate this maintenance schedule?")) {
                        deactivate.mutate(schedule.id);
                      }
                    }}
                  >
                    Deactivate
                  </button>
                </div>
              ) : null}
            </div>
          )}
        </article>
      ))}
      {canEdit && !retired ? (
        <form
          className="grid gap-2 rounded-lg border border-line bg-surface p-3 sm:grid-cols-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(draft, { onSuccess: () => setDraft(emptySchedule()) });
          }}
        >
          <h4 className="title-section sm:col-span-3">New schedule</h4>
          {fields(draft, setDraft, "New schedule")}
          <button className="desk-button-primary sm:col-span-3 sm:w-fit" type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating..." : "Create schedule"}
          </button>
        </form>
      ) : null}
      {[create.error, update.error, deactivate.error].map((error, index) =>
        error instanceof Error ? <p key={index} className="text-sm text-danger">{error.message}</p> : null,
      )}
    </section>
  );
}

function formatDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString();
}
