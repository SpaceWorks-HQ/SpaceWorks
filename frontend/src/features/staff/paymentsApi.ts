import type { QueryClient } from "@tanstack/react-query";

import { StructuredApiError, staffRequest } from "../../lib/api";

export const PAYMENT_SUBJECTS = [
  ["machine_service_request", "Machine service"],
  ["booking", "Booking"],
  ["event_registration", "Event registration"],
  ["makerspace_membership", "Membership dues"],
] as const;

export const PAYMENT_STATUSES = [
  ["pending", "Pending"],
  ["paid_online", "Paid online"],
  ["paid_offline", "Paid offline"],
  ["waived", "Waived"],
  ["canceled", "Canceled"],
] as const;

// Mirrors `apps/payments/serializers_reconciliation.RefundSerializer`. A refund is a row
// per ATTEMPT: pending until the provider answers, then succeeded or failed. Pending rows
// still count against the refundable balance, which is why `remainingRefundable` below
// subtracts them and not only `refunded_amount` (succeeded only).
export type RefundRow = {
  id: number;
  amount: string;
  currency: string;
  status: "pending" | "succeeded" | "failed";
  reason: string;
  created_at: string;
  settled_at: string | null;
};

export type PaymentRow = {
  id: number;
  subject_type: (typeof PAYMENT_SUBJECTS)[number][0];
  subject_id: number;
  subject_label: string;
  status: (typeof PAYMENT_STATUSES)[number][0];
  amount: string;
  currency: string;
  refunded_amount: string;
  refunds: RefundRow[];
  created_at: string;
  updated_at: string;
};

export function paymentListKey(makerspaceId: number, status: string, subject: string) {
  return ["payments", makerspaceId, status, subject] as const;
}

export function paymentListPath(makerspaceId: number, status: string, subject: string) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (subject) query.set("subject_type", subject);
  const suffix = query.toString();
  return `/admin/makerspace/${makerspaceId}/payments${suffix ? `?${suffix}` : ""}`;
}

export const SETTLEMENT_METHODS = [
  ["cash", "Cash"],
  ["upi", "UPI"],
  ["bank_transfer", "Bank transfer"],
  ["card_machine", "Card machine"],
  ["cheque", "Cheque"],
  ["other", "Other"],
] as const;

export type Settlement = { method: string; reference: string; received_at: string };

export function reconcilePayment(
  makerspaceId: number,
  action: "mark-offline" | "waive",
  ids: number[],
  bulk: boolean,
  settlement?: Settlement,
) {
  const base = `/admin/makerspace/${makerspaceId}/payments`;
  const path = bulk ? `${base}/bulk/${action}` : `${base}/${ids[0]}/${action}`;
  // Marking paid offline REQUIRES the receipt -- how and when the money arrived -- and
  // the API refuses without it. Waiving carries none, because no money moved.
  const body =
    action === "mark-offline"
      ? { ...(bulk ? { ids } : {}), settlement }
      : bulk
        ? { ids }
        : undefined;
  return staffRequest<PaymentRow | PaymentRow[]>(path, {
    method: "POST",
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

export function invalidatePaymentViews(queryClient: QueryClient, makerspaceId: number) {
  queryClient.invalidateQueries({ queryKey: ["payments", makerspaceId] });
  queryClient.invalidateQueries({ queryKey: ["operations-report", "payment-reconciliation"] });
  queryClient.invalidateQueries({ queryKey: ["dashboard", makerspaceId] });
}

export function refundPayment(
  makerspaceId: number,
  paymentId: number,
  body: { amount: string; reason: string },
) {
  return staffRequest<PaymentRow>(`/admin/makerspace/${makerspaceId}/payments/${paymentId}/refund`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** Amount still refundable: the payment minus every pending or succeeded refund. */
export function remainingRefundable(row: Pick<PaymentRow, "amount" | "refunds">) {
  const counted = (row.refunds ?? [])
    .filter((refund) => refund.status !== "failed")
    .reduce((total, refund) => total + Number(refund.amount), 0);
  return Math.max(0, Math.round((Number(row.amount) - counted) * 100) / 100);
}

// One readable sentence per backend code (`services_refunds.RefundNotAllowed` and
// `RefundProviderFailure`); anything else falls back to the API's own detail text.
const REFUND_ERRORS: Record<string, string> = {
  refund_not_online: "Only payments settled online can be refunded through the provider. Offline and waived charges are corrected in the till.",
  refund_exceeds_balance: "That amount is more than the remaining refundable balance of this payment.",
  refund_amount_invalid: "Enter a refund amount greater than zero, with at most two decimals.",
  refund_provider_failed: "The payment provider rejected the refund. No money was sent back; the failed attempt is recorded on the payment.",
};

export function refundErrorMessage(error: unknown) {
  if (error instanceof StructuredApiError && error.code && REFUND_ERRORS[error.code]) {
    return REFUND_ERRORS[error.code];
  }
  return error instanceof Error ? error.message : "Refund failed.";
}

export function formatMoney(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(Number(amount));
  } catch {
    return `${currency.toUpperCase()} ${amount}`;
  }
}
