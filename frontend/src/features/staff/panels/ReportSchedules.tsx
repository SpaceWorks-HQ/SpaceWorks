import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, ConfirmDialog } from "../../../components/ui";
import type { ReportCatalogItem } from "./operationsReportsConfig";
import { emptyScheduleForm, ReportScheduleForm, scheduleToForm } from "./ReportScheduleForm";
import {
  createSchedule,
  deleteSchedule,
  listChatDestinations,
  listSchedules,
  reportScheduleKeys,
  runScheduleNow,
  scheduleErrorText,
  updateSchedule,
  type ReportDelivery,
  type ReportSchedule,
  type ReportScheduleInput,
} from "./reportSchedulesApi";
import { Panel } from "./shared";

const when = (value: string | null) => (value ? new Date(value).toLocaleString() : "never");

/** Recurring exports. `reports` is the catalog already filtered to exportable + available. */
export function ReportSchedules({ makerspaceId, reports }: { makerspaceId: number; reports: ReportCatalogItem[] }) {
  const client = useQueryClient();
  const schedules = useQuery({ queryKey: reportScheduleKeys.list(makerspaceId), queryFn: () => listSchedules(makerspaceId) });
  const destinations = useQuery({
    queryKey: reportScheduleKeys.destinations(makerspaceId),
    queryFn: () => listChatDestinations(makerspaceId),
  });
  const [editing, setEditing] = useState<ReportSchedule | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<ReportSchedule | null>(null);
  const [runResult, setRunResult] = useState<{ id: number; delivery: ReportDelivery } | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: reportScheduleKeys.list(makerspaceId) });
  const save = useMutation({
    mutationFn: (input: ReportScheduleInput) => (editing ? updateSchedule(editing.id, input) : createSchedule(makerspaceId, input)),
    onSuccess: () => {
      setEditing(null);
      setCreating(false);
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: (schedule: ReportSchedule) => updateSchedule(schedule.id, { is_active: !schedule.is_active }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteSchedule(id),
    onSuccess: () => {
      setDeleting(null);
      refresh();
    },
  });
  const run = useMutation({
    mutationFn: (id: number) => runScheduleNow(id),
    onSuccess: (delivery, id) => {
      setRunResult({ id, delivery });
      refresh();
    },
  });
  const title = (key: string) => reports.find((report) => report.key === key)?.title ?? key;
  const destinationLabel = (id: number | null) =>
    id == null ? null : destinations.data?.find((destination) => destination.id === id)?.label ?? `destination #${id}`;
  const error = save.error ?? toggle.error ?? remove.error ?? run.error;
  const chatDestinations = (destinations.data ?? []).filter((destination) => destination.is_active);

  return (
    <Panel title="Scheduled reports">
      <p className="mb-3 text-sm text-muted">
        Generate an export on a cadence and deliver it to a chat destination, by email, or both. Files expire after the retention window.
      </p>
      {schedules.isLoading ? <p className="text-sm text-muted">Loading schedules…</p> : null}
      {schedules.isError ? <p className="text-sm text-danger" role="alert">{scheduleErrorText(schedules.error, "Could not load schedules.")}</p> : null}
      {schedules.data?.length === 0 ? <p className="text-sm text-muted">No schedules yet.</p> : null}
      {schedules.data?.map((schedule) => (
        <div key={schedule.id} className="border-t border-line py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="font-semibold text-ink">{title(schedule.report_key)}</p>
              <p className="text-xs text-muted">
                {schedule.cadence} · {schedule.format.toUpperCase()} · grain {schedule.grain}
                {schedule.filters?.window_days ? ` · last ${schedule.filters.window_days} days` : ""}
                {destinationLabel(schedule.destination) ? ` · ${destinationLabel(schedule.destination)}` : ""}
                {schedule.recipient_emails.length ? ` · ${schedule.recipient_emails.join(", ")}` : ""}
              </p>
              <p className="text-xs text-muted">Next run {when(schedule.next_run_at)} · last run {when(schedule.last_run_at)}</p>
              {schedule.last_delivery?.download_url ? (
                <a className="text-xs underline" href={schedule.last_delivery.download_url} target="_blank" rel="noreferrer">
                  Download last delivery
                </a>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={schedule.is_active ? "success" : "neutral"}>{schedule.is_active ? "Active" : "Paused"}</Badge>
              <button className="desk-button" type="button" disabled={run.isPending} onClick={() => run.mutate(schedule.id)}>Run now</button>
              <button className="desk-button" type="button" onClick={() => { setCreating(false); setEditing(schedule); }}>Edit</button>
              <button className="desk-button" type="button" disabled={toggle.isPending} onClick={() => toggle.mutate(schedule)}>
                {schedule.is_active ? "Pause" : "Resume"}
              </button>
              <button className="desk-button-danger" type="button" onClick={() => setDeleting(schedule)}>Delete</button>
            </div>
          </div>
          {runResult?.id === schedule.id ? (
            <p className="mt-2 text-sm text-ink" role="status">
              Run {runResult.delivery.status}.{" "}
              {runResult.delivery.download_url ? (
                <a className="underline" href={runResult.delivery.download_url} target="_blank" rel="noreferrer">Download the file</a>
              ) : runResult.delivery.error || "No file was produced."}
            </p>
          ) : null}
          {editing?.id === schedule.id ? (
            <div className="mt-3">
              <ReportScheduleForm
                key={schedule.id}
                reports={reports}
                destinations={chatDestinations}
                initial={scheduleToForm(schedule)}
                editing
                pending={save.isPending}
                onSubmit={(input) => save.mutate(input)}
                onCancel={() => setEditing(null)}
              />
            </div>
          ) : null}
        </div>
      ))}
      <div className="mt-4 border-t border-line pt-4">
        {creating ? (
          <ReportScheduleForm
            reports={reports}
            destinations={chatDestinations}
            initial={emptyScheduleForm(reports)}
            editing={false}
            pending={save.isPending}
            onSubmit={(input) => save.mutate(input)}
            onCancel={() => setCreating(false)}
          />
        ) : (
          <button className="desk-button-primary" type="button" disabled={!reports.length} onClick={() => { setEditing(null); setCreating(true); }}>
            New schedule
          </button>
        )}
      </div>
      {error ? <p className="mt-2 text-sm text-danger" role="alert">{scheduleErrorText(error, "Could not update the schedule.")}</p> : null}
      <ConfirmDialog
        open={Boolean(deleting)}
        title="Delete schedule"
        message={deleting ? `Delete the ${title(deleting.report_key)} schedule? Its stored deliveries are removed too.` : ""}
        confirmLabel="Delete schedule"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
        onCancel={() => setDeleting(null)}
      />
    </Panel>
  );
}
