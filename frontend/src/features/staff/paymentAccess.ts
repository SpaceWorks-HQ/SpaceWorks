import type { PaymentRow } from "./paymentsApi";

const SUBJECT_ACTION: Record<PaymentRow["subject_type"], string> = {
  machine_service_request: "manage_machines",
  booking: "manage_bookings",
  event_registration: "manage_events",
  makerspace_membership: "manage_makerspace",
  membership_term: "manage_makerspace",
  membership_request: "manage_makerspace",
  loan_deposit: "issue_request",
  loan_late_fee: "return_request",
};

/** Cash receipt authority is separate from forgiving debt or sending provider money. */
export function paymentAccess(actions: readonly string[], isSuperadmin: boolean, row: PaymentRow) {
  const subjectAuthority = isSuperadmin || actions.includes(SUBJECT_ACTION[row.subject_type]);
  const record = subjectAuthority || actions.includes("record_payment");
  return { record, waive: subjectAuthority, refund: row.status === "paid_offline" ? isSuperadmin || actions.includes("record_payment") : subjectAuthority };
}
