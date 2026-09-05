import type { MemberPayment } from "../../generated/api";

export type { MemberPayment };

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
        </li>
      ))}
    </ul>
  );
}
