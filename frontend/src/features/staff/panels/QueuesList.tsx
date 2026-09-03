import type React from "react";
import { useState } from "react";

import { StatusStepper, statusStageLabel } from "../../../components/ui/StatusStepper";
import { staffRequest } from "../../../lib/api";
import { evidenceErrorText } from "../evidenceUi";
import type { HardwareRequest } from "./Queues";
import { RequestTimelineBlock } from "./LoanTimeline";

type RequestActor = { username: string; role: string };
type RequestAttributionFields = {
  accepted_by?: RequestActor | null;
  issued_by?: RequestActor | null;
};

export function RequestList({ rows, actions, canViewAudit = false }: { rows: HardwareRequest[]; actions: (row: HardwareRequest) => React.ReactNode; canViewAudit?: boolean }) {
  const [timelineId, setTimelineId] = useState<number | null>(null);
  const [evidenceError, setEvidenceError] = useState<{ requestId: number; message: string } | null>(null);
  // Evidence object keys are never exposed; fetch a short-lived signed URL on click and open it.
  const openEvidence = async (requestId: number, evidenceId: number) => {
    setEvidenceError(null);
    try {
      const res = await staffRequest<{ url: string }>(`/admin/evidence/${evidenceId}`);
      window.open(res.url, "_blank", "noopener");
    } catch (error) {
      setEvidenceError({
        requestId,
        message: evidenceErrorText(error),
      });
    }
  };
  if (!rows.length) return <p className="text-sm text-ink/60">No requests.</p>;
  return (
    <div className="overflow-hidden rounded-md border border-line">
      {rows.map((row) => (
        <article key={row.id} className="min-w-0 border-b border-line bg-surface/50 p-3 last:border-b-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="title-section min-w-0 break-words"><span className="font-mono">#{row.id}</span> {row.requester_display || row.requester_username}</h3>
            <span className={`status-box ${statusBadgeClassName(row.status)}`}>
              {statusStageLabel(row.status)}
            </span>
            <div className="desk-actions ml-0 flex w-full flex-wrap gap-2 text-sm sm:ml-auto sm:w-auto">
              {actions(row)}
              {canViewAudit ? <button className="desk-button-ghost" type="button" onClick={() => setTimelineId((current) => (current === row.id ? null : row.id))}>{timelineId === row.id ? "Hide timeline" : "View timeline"}</button> : null}
            </div>
          </div>
          <div className="mt-3 max-w-md">
            <StatusStepper status={row.status} />
          </div>
          <p className="mt-2 text-sm text-muted">{row.requested_for || "No note"}</p>
          <RequestAttribution row={row} />
          {row.requester_contact_email || row.requester_contact_phone ? (
            <p className="mt-1 text-xs text-muted">
              <span className="font-medium text-ink">Contact: </span>
              {[row.requester_contact_email, row.requester_contact_phone].filter(Boolean).join(" Â· ")}
            </p>
          ) : null}
          {row.status === "rejected" && row.rejection_reason ? (
            <p className="mt-1 text-xs text-danger">
              <span className="font-medium">Rejected: </span>{row.rejection_reason}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-muted">
            {row.return_due_at ? `Due ${new Date(row.return_due_at).toLocaleString()}` : "No return due time set"}
            {row.return_reminder_sent_at ? ` Â· reminder sent ${new Date(row.return_reminder_sent_at).toLocaleString()}` : ""}
          </p>
          <div className="mt-2 space-y-0.5 text-xs text-ink/60">
            {row.items.map((item) => (
              <p key={item.id}>
                {item.product_name} x{item.requested_quantity}
                {item.storage_location ? <span className="text-muted"> Â· Shelf: {item.storage_location}</span> : null}
              </p>
            ))}
          </div>
          {row.issue_evidence_id || (row.return_evidence_ids?.length ?? 0) > 0 ? (
            <div className="desk-actions mt-2 flex flex-wrap gap-2 text-xs">
              {row.issue_evidence_id ? (
                <button className="desk-button-ghost" type="button" onClick={() => void openEvidence(row.id, row.issue_evidence_id as number)}>View issue photo</button>
              ) : null}
              {(row.return_evidence_ids ?? []).map((id, index) => (
                <button className="desk-button-ghost" key={id} type="button" onClick={() => void openEvidence(row.id, id)}>
                  View return photo{(row.return_evidence_ids?.length ?? 0) > 1 ? ` ${index + 1}` : ""}
                </button>
              ))}
              {evidenceError?.requestId === row.id ? (
                <p className="w-full text-sm text-danger" role="alert">{evidenceError.message}</p>
              ) : null}
            </div>
          ) : null}
          {timelineId === row.id ? <RequestTimelineBlock requestId={row.id} /> : null}
          {row.items.some((item) => item.damaged_quantity || item.missing_quantity || item.needs_fix_quantity) ? (
            <ul className="mt-1 text-xs text-danger">
              {row.items
                .filter((item) => item.damaged_quantity || item.missing_quantity || item.needs_fix_quantity)
                .map((item) => (
                  <li key={item.id}>
                    {item.product_name}:
                    {item.damaged_quantity ? ` ${item.damaged_quantity} damaged` : ""}
                    {item.missing_quantity ? ` ${item.missing_quantity} missing` : ""}
                    {item.needs_fix_quantity ? ` ${item.needs_fix_quantity} to-fix` : ""}
                  </li>
                ))}
            </ul>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function RequestAttribution({ row }: { row: HardwareRequest }) {
  const attributed = row as HardwareRequest & RequestAttributionFields;
  const parts = [
    attributed.accepted_by ? `Accepted by ${formatActor(attributed.accepted_by)}` : "",
    attributed.issued_by ? `Issued by ${formatActor(attributed.issued_by)}` : "",
  ].filter(Boolean);
  return parts.length ? <p className="mt-1 text-xs text-muted">{parts.join(" | ")}</p> : null;
}

function formatActor(actor: RequestActor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

function statusBadgeClassName(status: string) {
  switch (status) {
    case "returned":
      return "status-box-done";
    case "accepted":
    case "issued":
    case "partially_returned":
      return "status-box-active";
    case "rejected":
    case "closed_with_issue":
      return "status-box-danger";
    case "draft":
    case "pending_approval":
      return "status-box-pending";
    default:
      return "";
  }
}
