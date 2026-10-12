import type { MembershipPlan } from "./membershipPlansApi";

export type RenewalForm = { auto_renew: boolean; renewal_open_days: string; renewal_grace_days: string; renewal_retries: string; reminder_days_before: string; reminder_days_after: string };
export const emptyRenewal: RenewalForm = { auto_renew: false, renewal_open_days: "7", renewal_grace_days: "0", renewal_retries: "0", reminder_days_before: "14,7,1", reminder_days_after: "" };
export function planRenewal(plan: MembershipPlan): RenewalForm {
  return { auto_renew: plan.auto_renew ?? false, renewal_open_days: String(plan.renewal_open_days ?? 7), renewal_grace_days: String(plan.renewal_grace_days ?? 0), renewal_retries: String(plan.renewal_retries ?? 0), reminder_days_before: (plan.reminder_days_before ?? []).join(","), reminder_days_after: (plan.reminder_days_after ?? []).join(",") };
}
export function renewalInput(form: RenewalForm) {
  const days = (text: string) => [...new Set(text.split(",").map((part) => part.trim()).filter(Boolean).map(Number))].sort((a, b) => a - b);
  return { auto_renew: form.auto_renew, renewal_open_days: Number(form.renewal_open_days), renewal_grace_days: Number(form.renewal_grace_days), renewal_retries: Number(form.renewal_retries), reminder_days_before: days(form.reminder_days_before), reminder_days_after: days(form.reminder_days_after) };
}
export function validateRenewal(form: RenewalForm): string | null {
  for (const [name, max] of [["renewal_open_days", 365], ["renewal_grace_days", 365], ["renewal_retries", 3]] as const) {
    if (!/^\d+$/.test(form[name]) || Number(form[name]) > max) return `Enter a whole number between 0 and ${max} for renewal timing.`;
  }
  for (const value of [form.reminder_days_before, form.reminder_days_after]) {
    const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
    if (parts.length > 10 || parts.some((part) => !/^\d+$/.test(part) || Number(part) < 1 || Number(part) > 365)) return "Use up to ten reminder day offsets between 1 and 365, separated by commas.";
  }
  return null;
}
export function MembershipRenewalFields({ value, onChange }: { value: RenewalForm; onChange: (value: RenewalForm) => void }) {
  const labels = { renewal_open_days: "Open renewal days before expiry", renewal_grace_days: "Grace days", renewal_retries: "Checkout retries (maximum 3)", reminder_days_before: "Reminder days before expiry", reminder_days_after: "Reminder days after expiry" };
  return <fieldset className="grid gap-3 sm:col-span-3 sm:grid-cols-3 border-t border-line pt-3"><legend className="font-semibold">Renewal automation</legend>
    <label className="flex items-center gap-2 sm:col-span-3"><input type="checkbox" checked={value.auto_renew} onChange={(event) => onChange({ ...value, auto_renew: event.target.checked })} />Automatically open the next term after settlement</label>
    <p className="text-sm text-muted sm:col-span-3">Enable Automatic membership renewal and Membership lifecycle mail in features. Renewals record dues first; paid, waived and free renewals extend coverage. Grace delays borrowing lapse without revoking membership.</p>
    {(Object.keys(labels) as (keyof typeof labels)[]).map((key) => <label className="text-sm" key={key}>{labels[key]}<input className="desk-input mt-1" value={value[key]} inputMode={key.startsWith("reminder") ? "text" : "numeric"} onChange={(event) => onChange({ ...value, [key]: event.target.value })} /></label>)}
  </fieldset>;
}
