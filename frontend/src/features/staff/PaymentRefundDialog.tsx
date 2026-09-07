import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge, Field, Modal } from "../../components/ui";
import {
  formatMoney,
  invalidatePaymentViews,
  refundErrorMessage,
  refundPayment,
  remainingRefundable,
  type PaymentRow,
} from "./paymentsApi";

// Client-side mirror of `PaymentRefundRequestSerializer` (positive, two decimals) plus the
// balance rule the service enforces under the row lock. The server is still the authority:
// two staff refunding at once both pass here and one of them gets `refund_exceeds_balance`.
export function validateRefundAmount(raw: string, remaining: number): string | null {
  const trimmed = raw.trim();
  if (!/^\d+(\.\d{1,2})?$/.test(trimmed)) return "Enter an amount with at most two decimals.";
  const amount = Number(trimmed);
  if (amount <= 0) return "Refund amount must be greater than zero.";
  if (amount > remaining) return "Refund amount cannot exceed the remaining balance.";
  return null;
}

/** Mount with `key={payment.id}` so the form state resets per payment. */
export function PaymentRefundDialog({
  makerspaceId,
  payment,
  onClose,
}: {
  makerspaceId: number;
  payment: PaymentRow;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const remaining = remainingRefundable(payment);
  const [amount, setAmount] = useState(remaining.toFixed(2));
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => refundPayment(makerspaceId, payment.id, { amount: amount.trim(), reason: reason.trim() }),
    onSuccess: () => {
      invalidatePaymentViews(queryClient, makerspaceId);
      onClose();
    },
  });
  const submit = () => {
    const problem = validateRefundAmount(amount, remaining);
    setValidationError(problem);
    if (!problem) mutation.mutate();
  };
  const error = validationError ?? (mutation.error ? refundErrorMessage(mutation.error) : null);

  return (
    <Modal
      open
      onClose={onClose}
      title={`Refund payment ${formatMoney(payment.amount, payment.currency)}`}
      footer={(
        <div className="desk-actions flex flex-wrap justify-end gap-2">
          <button className="desk-button" type="button" disabled={mutation.isPending} onClick={onClose}>
            Cancel
          </button>
          <button
            className="desk-button-primary"
            type="submit"
            form="payment-refund-form"
            disabled={mutation.isPending || remaining <= 0}
          >
            {mutation.isPending ? "Refunding…" : "Send refund"}
          </button>
        </div>
      )}
    >
      <p className="text-sm text-muted">
        {payment.subject_label} · refunded so far {formatMoney(payment.refunded_amount, payment.currency)} ·
        remaining {formatMoney(remaining.toFixed(2), payment.currency)}
      </p>
      <form
        id="payment-refund-form"
        className="mt-3 grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field label="Refund amount" error={validationError ?? undefined}>
          <input
            className="desk-input"
            inputMode="decimal"
            value={amount}
            disabled={remaining <= 0}
            onChange={(event) => {
              setAmount(event.target.value);
              setValidationError(null);
            }}
          />
        </Field>
        <Field label="Reason (optional)">
          <input
            className="desk-input"
            maxLength={255}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
      </form>
      {error && !validationError ? (
        <p className="mt-3 text-sm text-danger" role="alert">{error}</p>
      ) : null}
      <RefundList refunds={payment.refunds} />
    </Modal>
  );
}

function RefundList({ refunds }: { refunds: PaymentRow["refunds"] }) {
  if (!refunds?.length) {
    return <p className="mt-4 text-xs text-muted">No refunds recorded for this payment.</p>;
  }
  return (
    <div className="mt-4">
      <h3 className="eyebrow">Refunds</h3>
      <ul className="mt-2 divide-y divide-line text-sm">
        {refunds.map((refund) => (
          <li key={refund.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="font-mono font-semibold text-ink">{formatMoney(refund.amount, refund.currency)}</span>
            <Badge tone={refund.status === "succeeded" ? "success" : refund.status === "failed" ? "danger" : "warn"}>
              {refund.status}
            </Badge>
            <span className="text-xs text-muted">
              {new Date(refund.created_at).toLocaleString()}
              {refund.reason ? ` · ${refund.reason}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
