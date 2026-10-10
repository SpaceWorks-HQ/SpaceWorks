import type { MemberPayment as GeneratedMemberPayment } from "../../generated/api";
import { useState } from "react";
import { DUE_OPTIONS, PaymentDueBadge } from "../staff/PaymentDueBadge";

// Additive API field until the coordinator regenerates the OpenAPI client.
export type MemberPayment = Omit<GeneratedMemberPayment, "refunded_amount" | "refunds" | "subject_type"> & {
  subject_type: GeneratedMemberPayment["subject_type"] | "membership_request";
  refunded_amount?: string | number; due_at?: string | null; due_date?: string | null; due_state?: string;
  refunds: Array<GeneratedMemberPayment["refunds"][number] & {
    method?: string; reference?: string; refunded_at?: string | null;
  }>;
};

export function MemberPaymentRows({
  payments,
  checkoutPaymentId,
  onCheckout,
}: {
  payments: MemberPayment[];
  checkoutPaymentId?: number;
  onCheckout: (paymentId: number) => void;
}) {
  const [dueFilter, setDueFilter] = useState("");
  return (
    <>
    <label className="grid gap-1 text-xs text-muted"><span>Payment due dates</span>
      <select className="desk-input" value={dueFilter} onChange={(event) => setDueFilter(event.target.value)}>
        <option value="">All due dates</option>{DUE_OPTIONS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </label>
    <ul className="mt-3 space-y-2 text-sm text-muted">
      {payments.filter((payment) => !dueFilter || payment.due_state === dueFilter).map((payment) => (
        <li key={payment.id}>
          <span className="font-medium text-ink">{payment.subject_label}</span>
          {" · "}{payment.status}
          {" "}<PaymentDueBadge payment={payment} />
          {payment.amount ? (
            <>
              {" · "}
              <span className="font-mono">
                {payment.amount} {(payment.currency ?? "").toUpperCase()}
              </span>
            </>
          ) : null}
          {payment.checkout_url ? (
            <>
              {" · "}
              <a className="desk-button-secondary ml-1" href={payment.checkout_url}>
                Pay now
              </a>
            </>
          ) : payment.status === "pending" && payment.online_payment_available ? (
            <>
              {" · "}
              <button
                className="desk-button-ghost ml-1"
                disabled={checkoutPaymentId !== undefined}
                onClick={() => onCheckout(payment.id)}
                type="button"
              >
                Generate payment link
              </button>
            </>
          ) : payment.status === "pending" ? (
            /* No rail behind this charge: the space takes it in person. Offering a
               payment link here called an endpoint that could not succeed. */
            <>{" · "}<span className="text-muted">Pay at the space</span></>
          ) : null}
          {payment.settlement ? (
            <>
              {" · "}
              <span className="text-muted">
                Received {new Date(payment.settlement.received_at).toLocaleDateString()}
                {" by "}
                {payment.settlement.method.replace(/_/g, " ")}
              </span>
            </>
          ) : null}
          {/* Money sent back on this charge. Pending refunds are shown too, so a payer
              who was told a refund is on its way can see it is recorded. */}
          {(payment.refunds ?? []).filter((refund) => refund.status !== "failed").map((refund, index) => (
            <span key={index} className="text-muted">
              {" · "}
              {refund.status === "succeeded" ? "Refunded" : "Refund pending"}{" "}
              <span className="font-mono">
                {refund.amount} {(refund.currency ?? "").toUpperCase()}
              </span>
              {refund.reason ? ` (${refund.reason})` : null}
              {refund.method ? ` by ${refund.method.replace(/_/g, " ")}` : ""}
              {refund.reference ? ` · ${refund.reference}` : ""}
            </span>
          ))}
        </li>
      ))}
    </ul>
    </>
  );
}
