import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { MakerspaceArchiveRequest } from "../../generated/api";
import { Badge } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";

const REASON_MAX_LENGTH = 2000;

const ERROR_MESSAGES: Record<string, string> = {
  pending_archive_request_exists: "An archive request is already pending for this makerspace.",
  archive_request_cooldown: "Please wait one hour after the last archive request before filing another.",
  superadmin_access_disabled: "Turn on superadmin access before requesting archival.",
  makerspace_already_archived: "This makerspace has already been archived.",
  archive_request_not_pending: "This archive request is no longer pending and cannot be withdrawn.",
};

type Props = {
  makerspaceId: number;
  canManageMakerspace: boolean;
};

export function MakerspaceArchiveRequestPanel({ makerspaceId, canManageMakerspace }: Props) {
  if (!canManageMakerspace) return null;
  return <AuthorizedArchiveRequestPanel makerspaceId={makerspaceId} />;
}

function AuthorizedArchiveRequestPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const queryKey = ["staff", "archive-requests", makerspaceId] as const;
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState("");
  const requests = useQuery({
    queryKey,
    queryFn: () => staffRequest<MakerspaceArchiveRequest[]>(
      `/admin/makerspace/${makerspaceId}/archive-requests`,
    ),
  });

  const create = useMutation({
    mutationFn: (value: string) => staffRequest<MakerspaceArchiveRequest>(
      `/admin/makerspace/${makerspaceId}/archive-requests`,
      { method: "POST", body: JSON.stringify({ reason: value }) },
    ),
    onSuccess: () => {
      setReason("");
      setFormError("");
      queryClient.invalidateQueries({ queryKey });
    },
  });
  const withdraw = useMutation({
    mutationFn: (requestId: number) => staffRequest<MakerspaceArchiveRequest>(
      `/admin/makerspace/${makerspaceId}/archive-requests/${requestId}/withdraw`,
      { method: "POST" },
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  const pending = requests.data?.find((request) => request.status === "pending");
  const history = requests.data?.filter((request) => request.status !== "pending") ?? [];
  const actionError = create.error ?? withdraw.error;

  return (
    <section className="min-w-0 rounded-md border border-line bg-bg p-4" aria-labelledby="archive-request-title">
      <div className="grid min-w-0 gap-2">
        <h3 id="archive-request-title" className="text-base font-semibold text-ink">
          Archive this makerspace
        </h3>
        <p className="max-w-3xl text-sm text-muted">
          Filing a request does not archive anything. A superadmin must confirm it first. Once
          archived, this makerspace disappears from the staff console and you lose access to it,
          so the outcome will arrive by email.
        </p>
      </div>

      {requests.isLoading ? (
        <p className="mt-4 text-sm text-muted" role="status">Loading archive requests…</p>
      ) : null}
      {requests.isError ? (
        <p className="mt-4 text-sm text-danger" role="alert">{errorMessage(requests.error)}</p>
      ) : null}

      {requests.isSuccess && pending ? (
        <div className="mt-4 rounded-md border border-warn bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-semibold text-ink">Pending request</h4>
              <Badge tone="warn">Pending</Badge>
            </div>
            <button
              className="desk-button min-h-11"
              type="button"
              disabled={withdraw.isPending}
              onClick={() => withdraw.mutate(pending.id)}
            >
              {withdraw.isPending ? "Withdrawing…" : "Withdraw"}
            </button>
          </div>
          <p className="mt-3 whitespace-pre-wrap text-sm text-ink">{pending.reason}</p>
          <p className="mt-2 text-xs text-muted">
            Filed by {pending.requested_by_username ?? "a staff member"} on{" "}
            <time dateTime={pending.requested_at}>{formatDateTime(pending.requested_at)}</time>
          </p>
        </div>
      ) : null}

      {requests.isSuccess && !pending ? (
        <form
          className="mt-4 grid max-w-3xl gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const trimmedReason = reason.trim();
            if (!trimmedReason) {
              setFormError("Enter a reason for requesting archival.");
              return;
            }
            setFormError("");
            create.mutate(trimmedReason);
          }}
        >
          <label className="grid gap-1 text-sm font-semibold text-ink" htmlFor="archive-request-reason">
            Reason for archival
            <textarea
              id="archive-request-reason"
              className="desk-input min-h-28 w-full resize-y focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              value={reason}
              required
              maxLength={REASON_MAX_LENGTH}
              rows={5}
              aria-describedby="archive-request-reason-help"
              onChange={(event) => {
                setReason(event.target.value);
                setFormError("");
                create.reset();
              }}
            />
          </label>
          <div id="archive-request-reason-help" className="flex flex-wrap justify-between gap-2 text-xs text-muted">
            <span>Do not include personal data.</span>
            <span>{reason.length} / {REASON_MAX_LENGTH}</span>
          </div>
          {formError ? <p className="text-sm text-danger" role="alert">{formError}</p> : null}
          <button
            className="desk-button-primary min-h-11 justify-self-start"
            type="submit"
            disabled={create.isPending}
          >
            {create.isPending ? "Filing request…" : "Request archival"}
          </button>
        </form>
      ) : null}

      {actionError ? (
        <p className="mt-3 text-sm text-danger" role="alert">{errorMessage(actionError)}</p>
      ) : null}

      {requests.isSuccess ? (
        <div className="mt-6 border-t border-line pt-4">
          <h4 className="text-sm font-semibold text-ink">Resolved history</h4>
          {history.length === 0 ? (
            <p className="mt-2 text-sm text-muted">No resolved archive requests.</p>
          ) : (
            <ul className="mt-3 grid gap-3">
              {history.map((request) => <HistoryRow key={request.id} request={request} />)}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

function HistoryRow({ request }: { request: MakerspaceArchiveRequest }) {
  const label = request.status[0].toUpperCase() + request.status.slice(1);
  const tone = request.status === "approved" ? "success" : request.status === "declined" ? "danger" : "neutral";
  return (
    <li className="rounded-md border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{label}</Badge>
        <span className="text-xs text-muted">
          Requested by {request.requested_by_username ?? "a staff member"} on {formatDateTime(request.requested_at)}
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm text-ink">{request.reason}</p>
      {request.resolution_note.trim() ? (
        <p className="mt-2 text-sm text-muted">Resolution note: {request.resolution_note}</p>
      ) : null}
      {request.resolved_at ? (
        <p className="mt-2 text-xs text-muted">
          Resolved by {request.resolved_by_username ?? "a superadmin"} on {formatDateTime(request.resolved_at)}
        </p>
      ) : null}
    </li>
  );
}

function errorMessage(error: unknown) {
  if (error instanceof StructuredApiError) {
    if (error.code && ERROR_MESSAGES[error.code]) return ERROR_MESSAGES[error.code];
    return error.detail ?? error.message;
  }
  return error instanceof Error ? error.message : "Unable to update archive requests.";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
