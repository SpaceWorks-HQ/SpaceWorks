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
          {payment.checkout_url ? (
            <>
              {" · "}
              <a className="desk-button-secondary ml-1" href={payment.checkout_url}>
                Pay now
              </a>
            </>
          ) : payment.status === "pending" ? (
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
          ) : null}
        </li>
      ))}
    </ul>
  );
}
