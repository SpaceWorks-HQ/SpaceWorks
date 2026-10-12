import type { MembershipRequest } from "../../generated/api";
import { CustomAnswersView } from "../forms/CustomAnswersView";
import type { AdmissionRequest, AdmissionVouch } from "../members/membershipAdmissionApi";
import { PaymentReconcileActions, type PaymentSummary } from "./PaymentReconcileActions";

export type ReviewMembershipRequest = Omit<MembershipRequest, "state"> & AdmissionRequest;

export function MembershipVouchers({ vouches }: { vouches?: AdmissionVouch[] }) {
  return vouches?.length ? <div className="mt-3"><h4 className="text-sm font-semibold text-ink">Vouchers</h4><ul className="text-sm text-muted">{vouches.map((vouch) => <li key={`${vouch.voucher_id}:${vouch.created_at}`}>{vouch.voucher_name} · recorded {new Date(vouch.created_at).toLocaleDateString()} · expires {new Date(vouch.expires_at).toLocaleDateString()}</li>)}</ul></div> : null;
}

export function MembershipAdmissionReview({ row, makerspaceId, manageable, canViewFinance, canRecordPayment, canWaive, approvePending, declinePending, selectedRole, onApprove, onDecline }: {
  row: ReviewMembershipRequest; makerspaceId: number; manageable: boolean;
  canViewFinance: boolean; canRecordPayment: boolean; canWaive: boolean;
  approvePending: boolean; declinePending: boolean; selectedRole: number | null;
  onApprove: () => void; onDecline: () => void;
}) {
  const reviewable = ["requested", "invited", "awaiting_vouches"].includes(row.state);
  const cancelable = reviewable || row.state === "awaiting_payment";
  return <div className="grid gap-3 border-t border-line py-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-sm text-ink">{row.user?.username ?? row.invite_email} · {row.kind} · {row.state}</span>
      {manageable && cancelable ? <div className="flex flex-wrap gap-2">
        {reviewable && (row.state !== "invited" || row.user) ? <button className="desk-button-primary" disabled={!selectedRole || approvePending} onClick={onApprove}>Approve</button> : null}
        <button className="desk-button" disabled={declinePending} onClick={onDecline}>{row.state === "invited" ? "Cancel invitation" : row.state === "awaiting_payment" ? "Cancel application" : "Decline"}</button>
      </div> : null}
    </div>
    {row.expires_at ? <p className="text-xs text-muted">Application expires {new Date(row.expires_at).toLocaleString()}</p> : null}
    {row.application_answers?.answers.length ? <details><summary className="cursor-pointer text-sm font-semibold text-ink">Application answers</summary><div className="mt-3"><CustomAnswersView snapshot={row.application_answers} /></div></details> : null}
    <MembershipVouchers vouches={row.vouches} />
    {row.state === "awaiting_payment" ? <p className="text-sm text-muted">Approved; activation waits for the admission charge to be settled.</p> : null}
    {canViewFinance && row.admission_payment ? <PaymentReconcileActions makerspaceId={makerspaceId} payment={row.admission_payment as PaymentSummary} canRecordPayment={canRecordPayment} canWaive={canWaive} invalidateKeys={[["members", makerspaceId], ["member"]]} /> : null}
  </div>;
}
