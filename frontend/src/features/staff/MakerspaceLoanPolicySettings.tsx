import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useStaffGet } from "./panels/shared";

export type LoanPolicy = {
  id: number; default_loan_days: number; loan_renewal_mode: "off" | "auto";
  loan_max_renewals: number; loan_renewal_days: number; loan_max_active: number;
  loan_max_items: number; loan_reminder_offsets_hours: number[]; loan_escalate_overdue_days: number;
};
const NUMBERS = [
  ["default_loan_days", "Loan period in days", 1, 365],
  ["loan_max_renewals", "Maximum renewals", 0, 100],
  ["loan_renewal_days", "Renewal length in days", 1, 365],
  ["loan_max_active", "Maximum active loans (0 = unlimited)", 0, undefined],
  ["loan_max_items", "Maximum outstanding items (0 = unlimited)", 0, undefined],
  ["loan_escalate_overdue_days", "Escalate to staff after days overdue (0 = off)", 0, 365],
] as const;

export function MakerspaceLoanPolicySettings({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const key = ["staff", "loan-policy", makerspaceId];
  const path = `/admin/makerspace/${makerspaceId}/return-policy`;
  const query = useStaffGet<LoanPolicy>(key, path);
  const [form, setForm] = useState<LoanPolicy | null>(null);
  const [offsets, setOffsets] = useState("0");
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (query.data) {
      setForm(query.data);
      setOffsets(query.data.loan_reminder_offsets_hours.join(", "));
    }
  }, [query.data]);
  const save = useMutation({
    mutationFn: (value: LoanPolicy) => staffRequest<LoanPolicy>(path, { method: "PATCH", body: JSON.stringify(value) }),
    onSuccess: () => Promise.all([
      client.invalidateQueries({ queryKey: key }),
      client.invalidateQueries({ queryKey: ["makerspace-settings", makerspaceId] }),
      client.invalidateQueries({ queryKey: ["staff", "makerspaces"] }),
    ]),
  });
  if (query.error) return <p role="alert" className="text-danger">{query.error.message}</p>;
  if (!form) return <p role="status" className="text-muted">Loading loan policy...</p>;
  return <form className="mt-5 grid gap-3 rounded-md border border-line p-4" onSubmit={(event) => {
    event.preventDefault();
    const parts = offsets.trim() ? offsets.split(",").map((part) => part.trim()) : [];
    const numbers = parts.map(Number);
    if (parts.some((part) => !/^-?\d+$/.test(part)) || numbers.length > 100 || new Set(numbers).size !== numbers.length || numbers.some((n) => n < -8760 || n > 8760)) {
      setProblem("Use up to 100 unique whole-hour offsets between -8760 and 8760.");
      return;
    }
    setProblem("");
    save.mutate({ ...form, loan_reminder_offsets_hours: numbers });
  }}>
    <h4 className="font-semibold text-ink">Loan policy</h4>
    <p className="text-sm text-muted">Enable Loan renewals and Borrow limits in Features to apply those rules. Renewals are refused for lapsed or restricted borrowers and when another borrower is waiting.</p>
    <div className="grid gap-3 sm:grid-cols-2">
      {NUMBERS.map(([field, label, min, max]) => <Field key={field} label={label}>
        <input className="desk-input" type="number" required min={min} max={max} step="1" value={form[field]} disabled={save.isPending} onChange={(event) => setForm({ ...form, [field]: Number(event.target.value) })} />
      </Field>)}
      <Field label="Renewal mode"><select className="desk-input" value={form.loan_renewal_mode} disabled={save.isPending} onChange={(event) => setForm({ ...form, loan_renewal_mode: event.target.value as LoanPolicy["loan_renewal_mode"] })}>
        <option value="off">Off</option><option value="auto">Automatic within policy</option>
      </select></Field>
      <Field label="Reminder offsets in hours" hint="Negative = before due; 0 = due; positive = overdue. Leave empty to disable borrower reminders.">
        <input className="desk-input" value={offsets} disabled={save.isPending} onChange={(event) => setOffsets(event.target.value)} />
      </Field>
    </div>
    <div><button className="desk-button-primary" type="submit" disabled={save.isPending}>{save.isPending ? "Saving..." : "Save loan policy"}</button></div>
    {problem || save.error ? <p className="text-sm text-danger" role="alert">{problem || save.error?.message}</p> : null}
    {save.isSuccess ? <p className="text-sm text-muted" role="status">Loan policy saved.</p> : null}
  </form>;
}
