import { useEffect, useState } from "react";

import { ErrorText, Modal } from "../../../components/ui";
import { FormFooter, submitForm } from "./QueuesModalShared";
import type { FormModalProps, RejectRequestValues, ReturnDueValues } from "./QueuesModalTypes";

export type {
  AssignIssueValues,
  IssueReject,
  RejectRequestValues,
  ReturnDueValues,
  ReturnRequestValues,
} from "./QueuesModalTypes";
export { AssignIssueModal } from "./QueuesAssignIssueModal";
export { ReturnRequestModal } from "./QueuesReturnRequestModal";

export function ReturnDueModal({
  row,
  open,
  pending,
  error,
  defaultValue,
  onClose,
  onSubmit,
}: FormModalProps<ReturnDueValues> & { defaultValue: string }) {
  const [returnDueAt, setReturnDueAt] = useState(defaultValue);

  useEffect(() => {
    if (open) setReturnDueAt(defaultValue);
  }, [defaultValue, open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Set due for request #${row.id}` : "Set due"}
      footer={<FormFooter formId="return-due-form" pending={pending} submitLabel="Save due date" onCancel={onClose} />}
    >
      <form id="return-due-form" className="grid gap-3" onSubmit={(event) => submitForm(event, () => onSubmit({ returnDueAt }))}>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Return due date and time</span>
          <input className="desk-input" type="datetime-local" value={returnDueAt} disabled={pending} onChange={(event) => setReturnDueAt(event.target.value)} />
        </label>
        <ErrorText message={error} />
      </form>
    </Modal>
  );
}

export function RejectRequestModal({ row, open, pending, error, onClose, onSubmit }: FormModalProps<RejectRequestValues>) {
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState("");

  useEffect(() => {
    if (open) {
      setReason("");
      setValidationError("");
    }
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={row ? `Reject request #${row.id}` : "Reject request"}
      footer={<FormFooter formId="reject-request-form" pending={pending} submitLabel="Reject request" onCancel={onClose} tone="danger" />}
    >
      <form id="reject-request-form" className="grid gap-3" onSubmit={(event) => submitForm(event, submitReject)}>
        <label className="grid gap-1 text-sm">
          <span className="font-medium text-ink">Reason</span>
          <textarea className="desk-input min-h-24 w-full resize-y" value={reason} disabled={pending} onChange={(event) => setReason(event.target.value)} />
        </label>
        <ErrorText message={validationError || error} />
      </form>
    </Modal>
  );

  function submitReject() {
    if (!reason.trim()) return setValidationError("Reason is required.");
    onSubmit({ reason: reason.trim() });
  }
}
