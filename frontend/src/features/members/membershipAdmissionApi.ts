import type { CustomAnswerSnapshot, CustomFormSchema } from "../forms/customFormTypes";
import { memberRequest, staffRequest, tenantPublicRequest } from "../../lib/api";

export type JoinMode = "open" | "approval" | "invite_only" | "vouch" | "closed";
export type PaymentTiming = "after_activation" | "before_activation";
export type AdmissionRecipe = "free_open" | "free_vouch" | "paid_approval" | "paid_invite_only" | "closed";
export type AdmissionSettings = {
  join_mode: JoinMode;
  vouches_required: number;
  voucher_min_tenure_days: number;
  voucher_pending_limit: number;
  vouch_expiry_days: number;
  vouch_replaces_approval: boolean;
  payment_timing: PaymentTiming;
  application_schema: CustomFormSchema;
  default_plan: number | null;
  joining_fee: string;
  joining_fee_currency: string;
  rejoin_dues_rule: "once" | "each_join";
  request_expiry_days: number;
};
export type PublicAdmission = Pick<AdmissionSettings, "join_mode" | "vouches_required" | "payment_timing" | "application_schema" | "joining_fee"> & {
  default_plan: { id: number; name: string; amount: string; currency: string } | null;
  joining_fee_currency?: string;
};
export type AdmissionPayment = { id: number; status: string; amount: string; currency: string };
export type AdmissionVouch = { voucher_id: number; voucher_name: string; created_at: string; expires_at: string };
export type AdmissionRequest = {
  id: number;
  state: string;
  application_answers?: CustomAnswerSnapshot | null;
  vouches?: AdmissionVouch[];
  admission_payment?: AdmissionPayment | null;
  expires_at?: string | null;
};

export const admissionKeys = {
  settings: (id: number) => ["membership-admission", id] as const,
  public: (slug: string) => ["member", slug, "admission-settings"] as const,
  own: (id: number) => ["member", id, "admission"] as const,
};
export const publicAdmission = (slug: string) => tenantPublicRequest<PublicAdmission>(slug, `/public/${slug}/membership-admission`);
export const admissionSettings = (id: number) => staffRequest<AdmissionSettings>(`/admin/makerspaces/${id}/membership-admission`);
export const saveAdmissionSettings = (id: number, input: Partial<AdmissionSettings> & { recipe?: AdmissionRecipe }) =>
  staffRequest<AdmissionSettings>(`/admin/makerspaces/${id}/membership-admission`, { method: "PATCH", body: JSON.stringify(input) });
export const ownAdmission = (id: number) => memberRequest<AdmissionRequest | null>(`/member/makerspaces/${id}/admission`);
export const cancelAdmission = (id: number, requestId: number) => memberRequest<AdmissionRequest>(`/member/makerspaces/${id}/admission/${requestId}/cancel`, { method: "POST" });
export const vouchForAdmission = (id: number, requestId: number) => memberRequest<Pick<AdmissionRequest, "id" | "state">>(`/member/makerspaces/${id}/admission/${requestId}/vouch`, { method: "POST" });
