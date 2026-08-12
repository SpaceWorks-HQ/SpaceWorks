import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Panel, useStaffGet, type Makerspace } from "./shared";
import { staffRequest } from "../../../lib/api";

type EmailLogStatus = "" | "sent" | "failed" | "pending" | "sending";

type EmailLogEntry = {
  id: number;
  to_email: string;
  subject: string;
  stream: string;
  event: string;
  audience: string;
  status: Exclude<EmailLogStatus, "">;
  error: string;
  attempts: number;
  created_at: string;
  sent_at: string | null;
};

type EmailLogResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: EmailLogEntry[];
};

export function EmailLogPanel({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<EmailLogStatus>("");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("page", String(page));
  const query = params.toString();
  const logs = useStaffGet<EmailLogResponse>(
    ["email-logs", makerspace.id, query],
    `/admin/makerspace/${makerspace.id}/email-logs?${query}`,
  );
  const retry = useMutation({
    mutationFn: (id: number) =>
      staffRequest<EmailLogEntry>(`/admin/makerspace/${makerspace.id}/email-logs/${id}/retry`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["email-logs", makerspace.id] });
    },
  });

  const updateStatus = (value: EmailLogStatus) => {
    setStatus(value);
    setPage(1);
  };

  return (
    <Panel title="Email log">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          aria-label="Email log status"
          className="desk-input w-full sm:w-48"
          value={status}
          onChange={(event) => updateStatus(event.target.value as EmailLogStatus)}
        >
          <option value="">All</option>
          <option value="sent">Sent</option>
          <option value="failed">Failed</option>
          <option value="pending">Pending</option>
          <option value="sending">Sending</option>
        </select>
      </div>
      {logs.isLoading ? <p className="mb-3 text-sm text-muted">Loading email logs...</p> : null}
      {logs.error ? <p className="mb-3 text-sm text-danger">{logs.error.message}</p> : null}
      {retry.error ? <p className="mb-3 text-sm text-danger">{retry.error.message}</p> : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="eyebrow border-b border-line">
            <tr>
              <th className="px-2 py-2">Created</th>
              <th className="px-2 py-2">To</th>
              <th className="px-2 py-2">Event</th>
              <th className="px-2 py-2">Status</th>
              <th className="px-2 py-2">Error</th>
              <th className="px-2 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {logs.data?.results.map((log) => (
              <tr key={log.id} className="border-b border-line/70 align-top">
                <td className="whitespace-nowrap px-2 py-2 text-muted">
                  {formatLocalDateTime(log.created_at)}
                </td>
                <td className="max-w-56 break-words px-2 py-2">{log.to_email}</td>
                <td className="px-2 py-2">
                  <span className="font-semibold">{log.event || "email"}</span>
                  <span className="ml-2 text-muted">{log.stream || "general"}</span>
                </td>
                <td className="px-2 py-2">
                  <span className={`status-box ${statusClassName(log.status)}`}>
                    {log.status}
                  </span>
                </td>
                <td className="max-w-72 break-words px-2 py-2 text-muted">
                  {log.status === "failed" ? truncate(log.error) : ""}
                </td>
                <td className="whitespace-nowrap px-2 py-2">
                  {log.status === "failed" || log.status === "sending" ? (
                    <button
                      className="desk-button-primary"
                      disabled={retry.isPending}
                      onClick={() => retry.mutate(log.id)}
                    >
                      Retry
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {logs.data && logs.data.results.length === 0 ? (
          <p className="py-4 text-sm text-muted">No email logs.</p>
        ) : null}
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <button
          className="desk-button-ghost"
          disabled={!logs.data?.previous}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
        >
          Previous
        </button>
        <span className="text-muted">
          Page {page}{" - "}{logs.data?.count ?? 0} total
        </span>
        <button
          className="desk-button-ghost"
          disabled={!logs.data?.next}
          onClick={() => setPage((current) => current + 1)}
        >
          Next
        </button>
      </div>
    </Panel>
  );
}

function statusClassName(status: EmailLogEntry["status"]) {
  if (status === "sent") return "status-box-done";
  if (status === "failed") return "status-box-danger";
  return "status-box-pending";
}

function truncate(value: string) {
  return value.length > 140 ? `${value.slice(0, 137)}...` : value;
}

function formatLocalDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
