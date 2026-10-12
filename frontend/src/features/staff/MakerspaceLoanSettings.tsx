import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useStaffGet } from "./panels/shared";

// The six loan fields of `MakerspacePaymentSettings` (backend `models_settings.py`), exposed
// through the same `/payment-settings` endpoint as the Stripe credentials. Money fields are
// major-unit decimals like `Payment.amount`; zero means "not charged" and a zero cap means
// "no cap". `loan_deposit_blocks_issue` turns a raised-and-payable-later deposit into a gate
// that the issue workflow checks before the QR/evidence Hard Rules (409 `deposit_required`).
export type LoanSettings = {
  loan_deposit_mode: "none" | "fixed" | "per_product";
  loan_deposit_amount: string;
  loan_late_fee_per_day: string;
  loan_late_fee_cap: string;
  loan_grace_days: number;
  loan_deposit_blocks_issue: boolean;
};

type LoanForm = {
  loan_deposit_mode: LoanSettings["loan_deposit_mode"];
  loan_deposit_amount: string;
  loan_late_fee_per_day: string;
  loan_late_fee_cap: string;
  loan_grace_days: string;
  loan_deposit_blocks_issue: boolean;
};

const MODES: [LoanSettings["loan_deposit_mode"], string][] = [
  ["none", "No deposit"],
  ["fixed", "Fixed amount per loan"],
  ["per_product", "Sum of product deposits"],
];

const MONEY = /^\d+(\.\d{1,2})?$/;

/** Field-level problems, keyed by form field; an empty object means the form is valid. */
export function validateLoanForm(form: LoanForm): Partial<Record<keyof LoanForm, string>> {
  const problems: Partial<Record<keyof LoanForm, string>> = {};
  for (const key of ["loan_deposit_amount", "loan_late_fee_per_day", "loan_late_fee_cap"] as const) {
    if (!MONEY.test(form[key].trim())) problems[key] = "Enter a non-negative amount with at most two decimals.";
  }
  if (!/^\d+$/.test(form.loan_grace_days.trim())) problems.loan_grace_days = "Enter a whole number of days (0 or more).";
  if (!MODES.some(([mode]) => mode === form.loan_deposit_mode)) problems.loan_deposit_mode = "Choose a deposit mode.";
  return problems;
}

function toForm(settings: LoanSettings): LoanForm {
  return {
    loan_deposit_mode: settings.loan_deposit_mode,
    loan_deposit_amount: settings.loan_deposit_amount,
    loan_late_fee_per_day: settings.loan_late_fee_per_day,
    loan_late_fee_cap: settings.loan_late_fee_cap,
    loan_grace_days: String(settings.loan_grace_days),
    loan_deposit_blocks_issue: settings.loan_deposit_blocks_issue,
  };
}

const EMPTY: LoanForm = {
  loan_deposit_mode: "none",
  loan_deposit_amount: "0.00",
  loan_late_fee_per_day: "0.00",
  loan_late_fee_cap: "0.00",
  loan_grace_days: "0",
  loan_deposit_blocks_issue: false,
};

/** Render only when the `payments.loans` feature is on; the parent owns that check. */
export function MakerspaceLoanSettings({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const queryKey = ["payment-settings", makerspaceId];
  const path = `/admin/makerspace/${makerspaceId}/payment-settings`;
  const settings = useStaffGet<LoanSettings>(queryKey, path);
  const [form, setForm] = useState<LoanForm>(EMPTY);
  const [problems, setProblems] = useState<Partial<Record<keyof LoanForm, string>>>({});
  useEffect(() => {
    if (settings.data) setForm(toForm(settings.data));
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      staffRequest<LoanSettings>(path, {
        method: "PATCH",
        body: JSON.stringify({
          loan_deposit_mode: form.loan_deposit_mode,
          loan_deposit_amount: form.loan_deposit_amount.trim(),
          loan_late_fee_per_day: form.loan_late_fee_per_day.trim(),
          loan_late_fee_cap: form.loan_late_fee_cap.trim(),
          loan_grace_days: Number(form.loan_grace_days.trim()),
          loan_deposit_blocks_issue: form.loan_deposit_blocks_issue,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });
  const set = <K extends keyof LoanForm>(key: K, value: LoanForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setProblems((current) => ({ ...current, [key]: undefined }));
  };
  const submit = () => {
    const next = validateLoanForm(form);
    setProblems(next);
    if (!Object.keys(next).length) save.mutate();
  };
  const busy = settings.isLoading || save.isPending;
  const depositOn = form.loan_deposit_mode !== "none";

  return (
    <form
      className="mt-4 rounded-md border border-line bg-surface p-3"
      aria-labelledby="loan-settings-heading"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <h4 id="loan-settings-heading" className="font-semibold text-ink">Loans</h4>
      <p className="mt-1 text-sm text-muted">
        Deposits are raised when a request is issued; late fees accrue per day after the grace period once a loan is overdue.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Field label="Deposit mode" error={problems.loan_deposit_mode}>
          <select
            className="desk-input"
            value={form.loan_deposit_mode}
            disabled={busy}
            onChange={(event) => set("loan_deposit_mode", event.target.value as LoanForm["loan_deposit_mode"])}
          >
            {MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        <Field
          label="Deposit amount"
          hint={form.loan_deposit_mode === "per_product" ? "Ignored: each product's own deposit is summed." : undefined}
          error={problems.loan_deposit_amount}
        >
          <input
            className="desk-input"
            inputMode="decimal"
            value={form.loan_deposit_amount}
            disabled={busy || form.loan_deposit_mode !== "fixed"}
            onChange={(event) => set("loan_deposit_amount", event.target.value)}
          />
        </Field>
        <Field label="Late fee per day" error={problems.loan_late_fee_per_day}>
          <input
            className="desk-input"
            inputMode="decimal"
            value={form.loan_late_fee_per_day}
            disabled={busy}
            onChange={(event) => set("loan_late_fee_per_day", event.target.value)}
          />
        </Field>
        <Field label="Late fee cap" hint="0 means no cap." error={problems.loan_late_fee_cap}>
          <input
            className="desk-input"
            inputMode="decimal"
            value={form.loan_late_fee_cap}
            disabled={busy}
            onChange={(event) => set("loan_late_fee_cap", event.target.value)}
          />
        </Field>
        <Field label="Grace days" hint="Days past the due date before late fees start." error={problems.loan_grace_days}>
          <input
            className="desk-input"
            inputMode="numeric"
            value={form.loan_grace_days}
            disabled={busy}
            onChange={(event) => set("loan_grace_days", event.target.value)}
          />
        </Field>
        <label className="flex items-start gap-3 self-end text-sm text-ink">
          <input
            className="mt-1 h-4 w-4"
            type="checkbox"
            checked={form.loan_deposit_blocks_issue}
            disabled={busy || !depositOn}
            onChange={(event) => set("loan_deposit_blocks_issue", event.target.checked)}
          />
          <span>
            <span className="font-semibold">Deposit blocks issue</span>
            <span className="block text-xs text-muted">When on, staff cannot issue a loan until its deposit is paid; the handover is refused with a deposit-required message.</span>
          </span>
        </label>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button className="desk-button-primary" type="submit" disabled={busy}>
          {save.isPending ? "Saving..." : "Save loan settings"}
        </button>
        {save.isSuccess && !save.isPending ? <span className="text-xs text-muted" role="status">Saved.</span> : null}
      </div>
      {settings.error || save.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">{(settings.error || save.error)?.message}</p>
      ) : null}
    </form>
  );
}
