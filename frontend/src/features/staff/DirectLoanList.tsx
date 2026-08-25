import { useState } from "react";

import { staffRequest } from "../../lib/api";
import { Panel } from "./StaffPanels";

export type DirectLoan = {
  id: number;
  public_token: string;
  status: string;
  target_label: string;
  container_label?: string | null;
  due_at: string | null;
  issued_by: { username: string; role: string } | null;
  issue_evidence_id?: number | null;
  return_evidence_id?: number | null;
  return_notes?: string;
  return_scan_required?: boolean;
  items: { product_name: string; quantity: number }[];
  return_items?: DirectLoanReturnItem[];
};

export type DirectLoanReturnItem = {
  item_id: number;
  product_name: string;
  remaining_quantity: number;
  tracking_mode: string;
  assets: { asset_id: number; asset_tag: string }[];
};

export function DirectLoanList({
  loans,
  onReturn,
}: {
  loans: DirectLoan[];
  onReturn: (loan: DirectLoan) => void;
}) {
  const [evidenceError, setEvidenceError] = useState<{ loanId: number; message: string } | null>(null);
  const openEvidence = async (loanId: number, evidenceId: number) => {
    setEvidenceError(null);
    try {
      const res = await staffRequest<{ url: string }>(`/admin/evidence/${evidenceId}`);
      window.open(res.url, "_blank", "noopener");
    } catch (error) {
      setEvidenceError({
        loanId,
        message: error instanceof Error ? error.message : "Could not load evidence photo.",
      });
    }
  };
  return (
    <Panel title="Direct handout loans">
      <div className="grid gap-2">
        {loans.map((loan) => (
          <article key={loan.id} className="rounded-md border border-line bg-surface p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-semibold text-ink">{loan.target_label}</h3>
                <p className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted">
                  <span className={`status-box ${directLoanStatusClassName(loan.status)}`}>
                    {directLoanStatusLabel(loan.status)}
                  </span>
                  {loan.container_label ? <span>given in: {loan.container_label}</span> : null}
                  {loan.due_at ? <span>due {new Date(loan.due_at).toLocaleString()}</span> : null}
                  {loan.issued_by ? <span>Issued by {loan.issued_by.username}</span> : null}
                </p>
              </div>
              {loan.status === "checked_out" ? (
                <button className="desk-button" onClick={() => onReturn(loan)}>
                  Return
                </button>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-muted">
              {loan.items.map((item) => `${item.product_name} x${item.quantity}`).join(", ")}
            </p>
            {loan.issue_evidence_id || (loan.status !== "checked_out" && loan.return_evidence_id) ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {loan.issue_evidence_id ? (
                  <button className="desk-button text-xs" type="button" onClick={() => void openEvidence(loan.id, loan.issue_evidence_id as number)}>
                    View issue photo
                  </button>
                ) : null}
                {loan.status !== "checked_out" && loan.return_evidence_id ? (
                  <button className="desk-button text-xs" type="button" onClick={() => void openEvidence(loan.id, loan.return_evidence_id as number)}>
                    View return photo
                  </button>
                ) : null}
                {loan.status !== "checked_out" && loan.return_notes ? <p className="text-xs text-muted">{loan.return_notes}</p> : null}
                {evidenceError?.loanId === loan.id ? (
                  <p className="w-full text-sm text-danger" role="alert">{evidenceError.message}</p>
                ) : null}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </Panel>
  );
}

function directLoanStatusClassName(status: string) {
  switch (status) {
    case "checked_out":
      return "status-box-active";
    case "returned":
      return "status-box-done";
    default:
      return "";
  }
}

function directLoanStatusLabel(status: string) {
  switch (status) {
    case "checked_out":
      return "Lent";
    case "returned":
      return "Returned";
    default:
      return status.replace(/_/g, " ");
  }
}
