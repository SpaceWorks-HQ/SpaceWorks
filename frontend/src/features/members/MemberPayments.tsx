import type { MemberPayment as GeneratedMemberPayment } from "../../generated/api";

// Additive API field until the coordinator regenerates the OpenAPI client.
export type MemberPayment = GeneratedMemberPayment & { refunded_amount?: string | number };

export function MemberPaymentRows({
  payments,
  checkoutPaymentId,
  onCheckout,
}: {
  payments: MemberPayment[];
  checkoutPaymentId?: number;
  onCheckout: (paymentId: number) => void;
}) {
  return (
    <ul className="mt-3 space-y-2 text-sm text-muted">
      {payments.map((payment) => (
        <li key={payment.id}>
          <span className="font-medium text-ink">{payment.subject_label}</span>
          {" · "}{payment.status}
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
            </span>
          ))}
        </li>
      ))}
    </ul>
  );
}
