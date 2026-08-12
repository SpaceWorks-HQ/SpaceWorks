import type { ChangeEvent, Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";

import { Spinner } from "../../components/ui/Spinner";
import type { PrintStatus } from "./publicApi";

export type TextInputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
};

const steps = [
  { key: "pending", label: "Requested" },
  { key: "accepted", label: "Accepted" },
  { key: "in_progress", label: "Printing" },
  { key: "completed", label: "Ready to collect" },
  { key: "collected", label: "Collected" },
];

const STEP_TONE_CLASSES = [
  "border-accent bg-accent text-on-accent",
  "border-warn bg-warn text-on-warn",
  "border-secondary bg-secondary text-on-secondary",
  "border-success bg-success text-on-success",
  "border-success bg-success text-on-success",
] as const;

export function TextInput({
  label,
  value,
  onChange,
  required = false,
  type = "text",
}: TextInputProps) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold tracking-wide text-muted">
        {label}
      </span>
      <input
        className="desk-input w-full"
        required={required}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function TextArea({
  label,
  value,
  onChange,
}: TextInputProps) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold tracking-wide text-muted">
        {label}
      </span>
      <textarea
        className="desk-input min-h-24 w-full"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

export function FilePicker({
  label,
  accept,
  files,
  setFiles,
}: {
  label: string;
  accept: string;
  files: File[];
  setFiles: Dispatch<SetStateAction<File[]>>;
}) {
  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    setFiles((current) => [...current, ...selected]);
    event.target.value = "";
  }

  return (
    <div>
      <label className="block">
        <span className="mb-1 block text-xs font-semibold tracking-wide text-muted">
          {label}
        </span>
        <input
          accept={accept}
          className="desk-input w-full"
          multiple
          type="file"
          onChange={addFiles}
        />
      </label>
      {files.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No files selected.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {files.map((file, index) => (
            <li
              className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              key={`${file.name}-${file.lastModified}-${index}`}
            >
              <span className="min-w-0 truncate text-ink">{file.name}</span>
              <button
                className="text-xs font-semibold text-danger"
                type="button"
                onClick={() =>
                  setFiles((current) =>
                    current.filter((_, fileIndex) => fileIndex !== index),
                  )
                }
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function printTimeLeftLabel(status: PrintStatus, now: number): string | null {
  if (
    status.status !== "in_progress" ||
    !status.started_at ||
    status.estimated_minutes == null
  ) {
    return null;
  }
  const finish = new Date(status.started_at).getTime() + status.estimated_minutes * 60_000;
  const remainingMs = finish - now;
  if (remainingMs <= 0) {
    return "Finishing up - past the estimate";
  }
  const totalMinutes = Math.ceil(remainingMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `~${hours}h ${minutes}m left` : `~${minutes}m left`;
}

function queuePositionDetail(status: PrintStatus): string {
  const approvedAhead = status.queue_approved_ahead ?? 0;
  const awaitingReviewAhead = status.queue_awaiting_review_ahead ?? 0;
  if (approvedAhead === 0 && awaitingReviewAhead === 0) {
    return "You're next in line";
  }
  return [
    `${approvedAhead} approved job${approvedAhead === 1 ? "" : "s"} ahead`,
    `${awaitingReviewAhead} awaiting review`,
  ].join(" / ");
}

export function StatusStepper({ status }: { status: PrintStatus }) {
  const currentIndex = steps.findIndex((step) => step.key === status.status);
  const terminalError = status.status === "rejected" || status.status === "failed";

  // Live tick so the printing countdown updates without a refetch.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (status.status !== "in_progress") return;
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [status.status]);
  const timeLeft = printTimeLeftLabel(status, now);

  if (terminalError) {
    return (
      <div className="status-box status-box-danger w-full justify-start">
        {status.title} is {status.status}.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {steps.map((step, index) => {
          const state =
            index < currentIndex
              ? STEP_TONE_CLASSES[index] ?? STEP_TONE_CLASSES[0]
              : index === currentIndex
                ? STEP_TONE_CLASSES[index] ?? STEP_TONE_CLASSES[0]
                : "";
          return (
            <div
              className={`status-box w-full ${state}`}
              key={step.key}
            >
              <p className="break-words font-semibold leading-tight">{step.label}</p>
            </div>
          );
        })}
      </div>
      {status.queue_position != null ? (
        <div
          aria-live="polite"
          className="rounded-xl border border-line bg-panel px-3 py-2 text-center shadow-soft"
        >
          <p className="text-sm font-semibold text-ink">
            #{status.queue_position} in the queue
          </p>
          <p className="mt-1 text-xs text-muted">
            {queuePositionDetail(status)}
          </p>
        </div>
      ) : null}
      {timeLeft ? (
        <p className="rounded-lg border border-accent bg-accent px-3 py-2 text-center text-sm font-semibold text-on-accent dark:bg-[#0b2a38] dark:text-[#7dd3fc]">
          {timeLeft}
        </p>
      ) : null}
      <p className="text-sm text-muted">
        Current status:{" "}
        <span className="font-semibold capitalize text-ink">
          {status.status.replace("_", " ")}
        </span>
      </p>
    </div>
  );
}

export function StatusResult({
  isPending,
  error,
  status,
}: {
  isPending: boolean;
  error: Error | null;
  status?: PrintStatus;
}) {
  if (isPending) {
    return (
      <div className="grid min-h-24 place-items-center">
        <Spinner />
      </div>
    );
  }

  if (error) {
    return (
      <p className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
        {error.message}
      </p>
    );
  }

  return status ? (
    <div className="space-y-3">
      <div>
        <h2 className="break-words text-lg font-semibold text-ink">{status.title}</h2>
        <p className="mt-1 text-xs text-muted">
          Created {new Date(status.created_at).toLocaleString()}
        </p>
      </div>
      <StatusStepper status={status} />
    </div>
  ) : null;
}
