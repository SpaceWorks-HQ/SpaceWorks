import { useState } from "react";

import { EmptyState, Skeleton } from "../../../../components/ui";
import { MaintenanceDocuments } from "./MaintenanceDocuments";
import { MaintenanceSchedules } from "./MaintenanceSchedules";
import {
  useLogMaintenance,
  useMaintenanceLogs,
  useMaintenanceSchedules,
  type LogInput,
  type MaintenanceSchedule,
} from "./maintenanceApi";

type MaintenanceTabProps = {
  makerspaceId: number;
  machineId: number;
  canEdit: boolean;
  canOperate: boolean;
  enabled: boolean;
  retired: boolean;
};

export function MaintenanceTab({
  makerspaceId, machineId, canEdit, canOperate, enabled, retired,
}: MaintenanceTabProps) {
  const [completing, setCompleting] = useState<MaintenanceSchedule | null>(null);
  const schedules = useMaintenanceSchedules(makerspaceId, machineId, enabled);
  const logs = useMaintenanceLogs(makerspaceId, machineId, enabled);

  if (schedules.isLoading || logs.isLoading) {
    return (
      <div className="grid gap-3" aria-label="Loading maintenance details">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const queryError = schedules.error ?? logs.error;
  if (queryError instanceof Error) {
    return <EmptyState title="Unable to load maintenance" description={queryError.message} />;
  }

  const scheduleRows = schedules.data?.results ?? [];
  const logRows = logs.data?.results ?? [];

  return (
    <div className="grid gap-5">
      <MaintenanceSchedules
        makerspaceId={makerspaceId}
        machineId={machineId}
        schedules={scheduleRows}
        canEdit={canEdit}
        retired={retired}
        onComplete={setCompleting}
      />
      {completing ? (
        <ScheduleCompletionForm
          key={completing.id}
          makerspaceId={makerspaceId}
          machineId={machineId}
          schedule={completing}
          onCancel={() => setCompleting(null)}
          onCompleted={() => setCompleting(null)}
        />
      ) : null}
      {canOperate && !retired ? (
        <MaintenanceLogForm makerspaceId={makerspaceId} machineId={machineId} />
      ) : null}
      <section className="grid gap-3" aria-labelledby="maintenance-history-title">
        <h3 id="maintenance-history-title" className="title-section">
          Maintenance history
        </h3>
        {!logRows.length ? (
          <EmptyState
            title="No maintenance logged"
            description="Completed maintenance records will appear here."
          />
        ) : null}
        {logRows.map((log) => (
          <details key={log.id} className="rounded-lg border border-line bg-bg p-3">
            <summary className="cursor-pointer list-none text-sm marker:hidden">
              <span className="flex flex-wrap items-start justify-between gap-2">
                <strong className="min-w-0 flex-1 text-ink">{log.summary}</strong>
                <span className="font-mono text-xs text-muted">{formatDateTime(log.performed_at)}</span>
              </span>
              {log.cost ? <span className="mt-1 block font-mono text-xs text-muted">Cost: {log.cost}</span> : null}
            </summary>
            <div className="mt-3 border-t border-line pt-3 text-sm text-muted">
              {log.parts_note ? (
                <p className="whitespace-pre-wrap break-words">{log.parts_note}</p>
              ) : <p>No parts notes.</p>}
              <MaintenanceDocuments
                machineId={machineId}
                logId={log.id}
                documents={log.documents}
                canDelete={canEdit}
                retired={retired}
              />
            </div>
          </details>
        ))}
      </section>
    </div>
  );
}

function ScheduleCompletionForm({ makerspaceId, machineId, schedule, onCancel, onCompleted }: {
  makerspaceId: number;
  machineId: number;
  schedule: MaintenanceSchedule;
  onCancel: () => void;
  onCompleted: () => void;
}) {
  const [summary, setSummary] = useState(schedule.description);
  const [performedAt, setPerformedAt] = useState("");
  const [cost, setCost] = useState("");
  const [partsNote, setPartsNote] = useState("");
  const [setIdle, setSetIdle] = useState(false);
  const complete = useLogMaintenance(makerspaceId, machineId);

  return (
    <section aria-labelledby={`complete-maintenance-${schedule.id}`}>
      <h3 id={`complete-maintenance-${schedule.id}`} className="title-section mb-3">
        Complete scheduled maintenance
      </h3>
      <form
        className="grid gap-2 rounded-lg border border-line bg-surface p-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          complete.mutate({
            summary: summary.trim(),
            performed_at: performedAt ? new Date(performedAt).toISOString() : undefined,
            cost: cost.trim() || null,
            parts_note: partsNote.trim(),
            set_idle: setIdle,
            schedule_id: schedule.id,
          }, { onSuccess: onCompleted });
        }}
      >
        <label className="eyebrow grid gap-1 sm:col-span-2">
          Summary
          <input className="desk-input" value={summary}
            onChange={(event) => setSummary(event.target.value)} required />
        </label>
        <label className="eyebrow grid gap-1">
          Performed at (optional)
          <input className="desk-input" type="datetime-local" value={performedAt}
            onChange={(event) => setPerformedAt(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">
          Cost (optional)
          <input className="desk-input" type="number" min="0" step="0.01" value={cost}
            onChange={(event) => setCost(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1 sm:col-span-2">
          Parts and notes (optional)
          <textarea className="desk-input min-h-20" value={partsNote}
            onChange={(event) => setPartsNote(event.target.value)} />
        </label>
        <label className="eyebrow flex items-center gap-2 sm:col-span-2">
          <input type="checkbox" checked={setIdle}
            onChange={(event) => setSetIdle(event.target.checked)} />
          Set machine status to idle
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <button className="desk-button-primary" type="submit"
            disabled={complete.isPending || !summary.trim()}>
            {complete.isPending ? "Completing..." : "Complete maintenance"}
          </button>
          <button className="desk-button-ghost" type="button" onClick={onCancel} disabled={complete.isPending}>
            Cancel
          </button>
        </div>
      </form>
      {complete.error instanceof Error ? (
        <p className="mt-2 text-sm text-danger" role="alert">{complete.error.message}</p>
      ) : null}
    </section>
  );
}

function MaintenanceLogForm({ makerspaceId, machineId }: {
  makerspaceId: number;
  machineId: number;
}) {
  const [summary, setSummary] = useState("");
  const [performedAt, setPerformedAt] = useState("");
  const [cost, setCost] = useState("");
  const [partsNote, setPartsNote] = useState("");
  const [setIdle, setSetIdle] = useState(false);
  const log = useLogMaintenance(makerspaceId, machineId);

  const reset = () => {
    setSummary("");
    setPerformedAt("");
    setCost("");
    setPartsNote("");
    setSetIdle(false);
  };

  return (
    <section aria-labelledby="log-maintenance-title">
      <h3 id="log-maintenance-title" className="title-section mb-3">
        Log maintenance
      </h3>
      <form
        className="grid gap-2 rounded-lg border border-line bg-surface p-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          const input: LogInput = {
            summary: summary.trim(),
            performed_at: performedAt ? new Date(performedAt).toISOString() : undefined,
            cost: cost.trim() || null,
            parts_note: partsNote.trim(),
            set_idle: setIdle,
          };
          log.mutate(input, { onSuccess: reset });
        }}
      >
        <label className="eyebrow grid gap-1 sm:col-span-2">
          Summary
          <input className="desk-input" value={summary}
            onChange={(event) => setSummary(event.target.value)} required />
        </label>
        <label className="eyebrow grid gap-1">
          Performed at (optional)
          <input className="desk-input" type="datetime-local" value={performedAt}
            onChange={(event) => setPerformedAt(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">
          Cost (optional)
          <input className="desk-input" type="number" min="0" step="0.01" value={cost}
            onChange={(event) => setCost(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1 sm:col-span-2">
          Parts and notes (optional)
          <textarea className="desk-input min-h-20" value={partsNote}
            onChange={(event) => setPartsNote(event.target.value)} />
        </label>
        <label className="eyebrow flex items-center gap-2 sm:col-span-2">
          <input type="checkbox" checked={setIdle}
            onChange={(event) => setSetIdle(event.target.checked)} />
          Set machine status to idle
        </label>
        <button className="desk-button-primary justify-self-start" type="submit"
          disabled={log.isPending || !summary.trim()}>
          {log.isPending ? "Logging..." : "Log maintenance"}
        </button>
      </form>
      {log.error instanceof Error ? (
        <p className="mt-2 text-sm text-danger" role="alert">{log.error.message}</p>
      ) : null}
    </section>
  );
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
