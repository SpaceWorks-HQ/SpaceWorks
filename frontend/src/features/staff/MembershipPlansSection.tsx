import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, Field } from "../../components/ui";
import {
  PLAN_INTERVALS,
  createPlan,
  listPlans,
  membershipPlanKeys,
  planErrorText,
  planIntervalLabel,
  updatePlan,
  type MembershipPlan,
  type MembershipPlanInput,
  type PlanInterval,
} from "./membershipPlansApi";
import { formatMoney } from "./paymentsApi";
import { Panel } from "./panels/shared";

type PlanForm = {
  name: string;
  interval: PlanInterval;
  custom_days: string;
  amount: string;
  currency: string;
  is_active: boolean;
};

const EMPTY: PlanForm = { name: "", interval: "monthly", custom_days: "", amount: "0.00", currency: "usd", is_active: true };

/** Mirrors `MembershipPlanSerializer.validate`: custom days only with the custom interval. */
export function validatePlanForm(form: PlanForm): string | null {
  if (!form.name.trim()) return "Give the plan a name.";
  if (!/^\d+(\.\d{1,2})?$/.test(form.amount.trim())) return "Enter a non-negative amount with at most two decimals.";
  if (!/^[A-Za-z]{3}$/.test(form.currency.trim())) return "Use a three-letter ISO 4217 currency code.";
  if (form.interval === "custom_days" && !/^[1-9]\d*$/.test(form.custom_days.trim())) {
    return "A custom interval needs a whole number of days (1 or more).";
  }
  return null;
}

function toInput(form: PlanForm): MembershipPlanInput {
  return {
    name: form.name.trim(),
    interval: form.interval,
    // The serializer refuses a day count on a non-custom interval, so send null there.
    custom_days: form.interval === "custom_days" ? Number(form.custom_days.trim()) : null,
    amount: form.amount.trim(),
    currency: form.currency.trim().toLowerCase(),
    is_active: form.is_active,
  };
}

function toForm(plan: MembershipPlan): PlanForm {
  return {
    name: plan.name,
    interval: plan.interval,
    custom_days: plan.custom_days == null ? "" : String(plan.custom_days),
    amount: plan.amount,
    currency: plan.currency,
    is_active: plan.is_active,
  };
}

export function MembershipPlansSection({ makerspaceId }: { makerspaceId: number }) {
  const client = useQueryClient();
  const plans = useQuery({ queryKey: membershipPlanKeys.plans(makerspaceId), queryFn: () => listPlans(makerspaceId) });
  const [editing, setEditing] = useState<MembershipPlan | null>(null);
  const [form, setForm] = useState<PlanForm>(EMPTY);
  const [problem, setProblem] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: membershipPlanKeys.plans(makerspaceId) });
  const save = useMutation({
    mutationFn: () => (editing ? updatePlan(editing.id, toInput(form)) : createPlan(makerspaceId, toInput(form))),
    onSuccess: () => {
      setEditing(null);
      setForm(EMPTY);
      refresh();
    },
  });
  const toggleActive = useMutation({
    mutationFn: (plan: MembershipPlan) => updatePlan(plan.id, { is_active: !plan.is_active }),
    onSuccess: refresh,
  });
  const set = <K extends keyof PlanForm>(key: K, value: PlanForm[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    setProblem(null);
  };
  const submit = () => {
    const next = validatePlanForm(form);
    setProblem(next);
    if (!next) save.mutate();
  };
  const startEdit = (plan: MembershipPlan) => {
    setEditing(plan);
    setForm(toForm(plan));
    setProblem(null);
  };
  const cancelEdit = () => {
    setEditing(null);
    setForm(EMPTY);
    setProblem(null);
  };
  const error = problem ?? (save.error ? planErrorText(save.error, "Could not save the plan.") : null)
    ?? (toggleActive.error ? planErrorText(toggleActive.error, "Could not update the plan.") : null);

  return (
    <Panel title="Membership plans">
      <p className="mb-3 text-sm text-muted">
        Plans price a membership term. Members are put on a plan from the roster ("Terms"); a plan with terms cannot be deleted, only deactivated.
      </p>
      {plans.isLoading ? <p className="text-sm text-muted">Loading plans…</p> : null}
      {plans.isError ? <p className="text-sm text-danger" role="alert">{planErrorText(plans.error, "Could not load plans.")}</p> : null}
      {plans.data?.length === 0 ? <p className="text-sm text-muted">No plans yet.</p> : null}
      {plans.data?.map((plan) => (
        <div key={plan.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-line py-3">
          <div>
            <p className="font-semibold text-ink">{plan.name}</p>
            <p className="text-xs text-muted">{planIntervalLabel(plan)} · {formatMoney(plan.amount, plan.currency)}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={plan.is_active ? "success" : "neutral"}>{plan.is_active ? "Active" : "Inactive"}</Badge>
            <button className="desk-button" type="button" onClick={() => startEdit(plan)}>Edit</button>
            <button className="desk-button" type="button" disabled={toggleActive.isPending} onClick={() => toggleActive.mutate(plan)}>
              {plan.is_active ? "Deactivate" : "Activate"}
            </button>
          </div>
        </div>
      ))}
      <form
        className="mt-4 grid gap-2 border-t border-line pt-4 sm:grid-cols-3"
        aria-label={editing ? `Edit plan ${editing.name}` : "New membership plan"}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field label="Plan name" className="sm:col-span-3">
          <input className="desk-input" maxLength={120} value={form.name} onChange={(event) => set("name", event.target.value)} />
        </Field>
        <Field label="Interval">
          <select className="desk-input" value={form.interval} onChange={(event) => set("interval", event.target.value as PlanInterval)}>
            {PLAN_INTERVALS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </Field>
        <Field label="Custom days" hint={form.interval === "custom_days" ? undefined : "Only for a custom interval."}>
          <input
            className="desk-input"
            inputMode="numeric"
            value={form.custom_days}
            disabled={form.interval !== "custom_days"}
            onChange={(event) => set("custom_days", event.target.value)}
          />
        </Field>
        <label className="flex items-center gap-2 self-end pb-2 text-sm text-ink">
          <input className="h-4 w-4" type="checkbox" checked={form.is_active} onChange={(event) => set("is_active", event.target.checked)} />
          Active
        </label>
        <Field label="Amount">
          <input className="desk-input" inputMode="decimal" value={form.amount} onChange={(event) => set("amount", event.target.value)} />
        </Field>
        <Field label="Currency">
          <input className="desk-input" maxLength={3} value={form.currency} onChange={(event) => set("currency", event.target.value.toLowerCase())} />
        </Field>
        <div className="flex items-end gap-2">
          <button className="desk-button-primary" type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save plan" : "Create plan"}
          </button>
          {editing ? <button className="desk-button" type="button" onClick={cancelEdit}>Cancel</button> : null}
        </div>
      </form>
      {error ? <p className="mt-2 text-sm text-danger" role="alert">{error}</p> : null}
    </Panel>
  );
}
