import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import { admissionKeys, admissionSettings, saveAdmissionSettings, type AdmissionRecipe, type AdmissionSettings, type JoinMode, type PaymentTiming } from "../members/membershipAdmissionApi";
import { listPlans, membershipPlanKeys } from "./membershipPlansApi";

export const ADMISSION_RECIPES: [AdmissionRecipe, string][] = [
  ["free_open", "Free + open"], ["free_vouch", "Free + vouch"], ["paid_approval", "Paid + approval"], ["paid_invite_only", "Paid + invite-only"], ["closed", "Closed"],
];

export function admissionRecipeDraft(settings: AdmissionSettings, recipe: AdmissionRecipe): AdmissionSettings {
  const defaults = { ...settings, application_schema: null, vouches_required: 1, voucher_min_tenure_days: 30, voucher_pending_limit: 3, vouch_expiry_days: 30, vouch_replaces_approval: false };
  if (recipe === "closed") return { ...defaults, join_mode: "closed", default_plan: null, joining_fee: "0.00", payment_timing: "after_activation" };
  if (recipe === "free_open" || recipe === "free_vouch") return { ...defaults, join_mode: recipe === "free_open" ? "open" : "vouch", default_plan: null, joining_fee: "0.00", payment_timing: "after_activation" };
  return { ...defaults, join_mode: recipe === "paid_approval" ? "approval" : "invite_only", payment_timing: "before_activation" };
}

export function MembershipAdmissionSettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: admissionKeys.settings(makerspaceId), queryFn: () => admissionSettings(makerspaceId) });
  const plans = useQuery({ queryKey: membershipPlanKeys.plans(makerspaceId), queryFn: () => listPlans(makerspaceId) });
  const [draft, setDraft] = useState<AdmissionSettings | null>(null);
  const [recipe, setRecipe] = useState<AdmissionRecipe | "">("");
  const value = draft ?? settings.data;
  const save = useMutation({ mutationFn: () => saveAdmissionSettings(makerspaceId, { ...value!, ...(recipe ? { recipe } : {}) }), onSuccess: (data) => {
    client.setQueryData(admissionKeys.settings(makerspaceId), data);
    setDraft(null); setRecipe("");
    void client.invalidateQueries({ queryKey: ["makerspace-settings", makerspaceId] });
    void client.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
    void client.invalidateQueries({ queryKey: ["member"] });
    void client.invalidateQueries({ queryKey: ["walk-in-admission", makerspaceId] });
  } });
  if (settings.isPending) return <p className="text-sm text-muted">Loading admission settings…</p>;
  if (settings.isError || !value) return <p className="text-sm text-danger" role="alert">{settings.error?.message ?? "Unable to load admission settings."}</p>;
  const update = <K extends keyof AdmissionSettings>(key: K, next: AdmissionSettings[K]) => { setDraft({ ...value, [key]: next }); save.reset(); };
  const activePlans = plans.data?.filter((plan) => plan.is_active) ?? [];
  return <form className="grid min-w-0 gap-4 rounded-md border border-line bg-bg p-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <div><h3 className="title-panel">Membership admission</h3><p className="mt-1 text-sm text-muted">Choose a recipe, then adjust its conditions. Saving updates current admission conditions. Submitted answers and raised charges keep their snapshots. Closed refuses every new joining path.</p></div>
    <fieldset disabled={save.isPending} className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1 text-sm text-ink">Admission recipe<select className="desk-input" value={recipe} onChange={(event) => {
          const next = event.target.value as AdmissionRecipe | "";
          setRecipe(next);
          if (next) setDraft(admissionRecipeDraft(value, next));
          save.reset();
        }}><option value="">Custom settings</option>{ADMISSION_RECIPES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label className="grid gap-1 text-sm text-ink">Join mode<select className="desk-input" value={value.join_mode} onChange={(event) => update("join_mode", event.target.value as JoinMode)}><option value="open">Open</option><option value="approval">Approval</option><option value="invite_only">Invite-only</option><option value="vouch">Vouch</option><option value="closed">Closed</option></select></label>
        <label className="grid gap-1 text-sm text-ink">Payment timing<select className="desk-input" value={value.payment_timing} onChange={(event) => update("payment_timing", event.target.value as PaymentTiming)}><option value="after_activation">Activate then charge</option><option value="before_activation">Pay before activation</option></select></label>
        <label className="grid gap-1 text-sm text-ink">Default admission plan<select className="desk-input" value={value.default_plan ?? ""} disabled={plans.isPending || plans.isError} onChange={(event) => update("default_plan", event.target.value ? Number(event.target.value) : null)}><option value="">No default plan</option>{activePlans.map((plan) => <option key={plan.id} value={plan.id}>{plan.name} · {plan.amount} {plan.currency.toUpperCase()}</option>)}</select></label>
        <label className="grid gap-1 text-sm text-ink">Joining fee<input className="desk-input" type="number" required min="0" step="0.01" value={value.joining_fee} onChange={(event) => update("joining_fee", event.target.value)} /></label>
        <label className="grid gap-1 text-sm text-ink">Joining fee currency<input className="desk-input" required pattern="[a-zA-Z]{3}" maxLength={3} value={value.joining_fee_currency} onChange={(event) => update("joining_fee_currency", event.target.value.toLowerCase())} /></label>
        <label className="grid gap-1 text-sm text-ink">Re-join dues<select className="desk-input" value={value.rejoin_dues_rule} onChange={(event) => update("rejoin_dues_rule", event.target.value as AdmissionSettings["rejoin_dues_rule"])}><option value="once">Once per person</option><option value="each_join">On every re-join</option></select></label>
        <NumberField label="Application expiry (days)" value={value.request_expiry_days} min={1} onChange={(next) => update("request_expiry_days", next)} />
      </div>
      {plans.isError ? <p role="alert" className="text-sm text-danger">{plans.error.message}</p> : null}
      {recipe.startsWith("paid_") && !Number(value.joining_fee) && !activePlans.some((plan) => plan.id === value.default_plan && Number(plan.amount) > 0) ? <p className="text-sm text-warn">Choose a priced default plan or joining fee for this paid recipe.</p> : null}
      <fieldset className="grid gap-3 rounded border border-line p-3"><legend className="text-sm font-semibold text-ink">Vouch rules</legend>
        <p className="text-sm text-muted">Vouchers must be active, unrestricted members. Vouches record accountability without automatically restricting anyone.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label="Vouches required" min={1} value={value.vouches_required} onChange={(next) => update("vouches_required", next)} />
          <NumberField label="Minimum voucher tenure (days)" min={0} value={value.voucher_min_tenure_days} onChange={(next) => update("voucher_min_tenure_days", next)} />
          <NumberField label="Pending applicants per voucher" min={1} value={value.voucher_pending_limit} onChange={(next) => update("voucher_pending_limit", next)} />
          <NumberField label="Vouch expiry (days)" min={1} value={value.vouch_expiry_days} onChange={(next) => update("vouch_expiry_days", next)} />
        </div>
        <label className="flex gap-2 text-sm text-ink"><input type="checkbox" checked={value.vouch_replaces_approval} onChange={(event) => update("vouch_replaces_approval", event.target.checked)} />Vouches replace staff approval</label>
      </fieldset>
      <CustomFormBuilder value={value.application_schema} onChange={(schema) => update("application_schema", schema)} legend="Membership application questions" emptyMessage="No application questions. Applicants submit their verified account identity." />
    </fieldset>
    <button className="desk-button w-fit" type="submit" disabled={save.isPending}>{save.isPending ? "Saving…" : "Save admission settings"}</button>
    {save.isSuccess ? <p role="status" className="text-sm text-success">Admission settings saved.</p> : null}
    {save.error ? <p role="alert" className="text-sm text-danger">{save.error.message}</p> : null}
  </form>;
}

function NumberField({ label, value, min, onChange }: { label: string; value: number; min: number; onChange: (value: number) => void }) {
  return <label className="grid gap-1 text-sm text-ink">{label}<input className="desk-input" type="number" required min={min} step="1" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}
