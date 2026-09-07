import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge, Field, Modal } from "../../components/ui";
import {
  cancelTerm,
  listPlans,
  listTerms,
  membershipPlanKeys,
  planErrorText,
  planIntervalLabel,
  startTerm,
} from "./membershipPlansApi";
import { formatMoney } from "./paymentsApi";

/** Mount with `key={membershipId}`; the plan choice is per dialog, not per panel. */
export function MemberTermsDialog({
  makerspaceId,
  membershipId,
  memberName,
  onClose,
}: {
  makerspaceId: number;
  membershipId: number;
  memberName: string;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const terms = useQuery({ queryKey: membershipPlanKeys.terms(membershipId), queryFn: () => listTerms(membershipId) });
  const plans = useQuery({ queryKey: membershipPlanKeys.plans(makerspaceId), queryFn: () => listPlans(makerspaceId) });
  const activePlans = plans.data?.filter((plan) => plan.is_active) ?? [];
  const [planId, setPlanId] = useState<number | null>(null);
  const selectedPlan = planId ?? activePlans[0]?.id ?? null;
  const refresh = () => {
    client.invalidateQueries({ queryKey: membershipPlanKeys.terms(membershipId) });
    // Starting a term raises the plan's charge, so the roster's payment summary changes too.
    client.invalidateQueries({ queryKey: ["members", makerspaceId] });
    client.invalidateQueries({ queryKey: ["payments", makerspaceId] });
  };
  const start = useMutation({
    mutationFn: () => startTerm(membershipId, selectedPlan!),
    onSuccess: refresh,
  });
  const cancel = useMutation({ mutationFn: (termId: number) => cancelTerm(termId), onSuccess: refresh });
  const error = start.error ?? cancel.error;

  return (
    <Modal
      open
      onClose={onClose}
      title={`Membership terms for ${memberName}`}
      footer={(
        <div className="desk-actions flex justify-end">
          <button className="desk-button" type="button" onClick={onClose}>Close</button>
        </div>
      )}
    >
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (selectedPlan) start.mutate();
        }}
      >
        <Field label="Plan" className="min-w-48 flex-1">
          <select
            className="desk-input"
            value={selectedPlan ?? ""}
            disabled={!activePlans.length}
            onChange={(event) => setPlanId(Number(event.target.value))}
          >
            {!activePlans.length ? <option value="">{plans.isLoading ? "Loading plans…" : "No active plans"}</option> : null}
            {activePlans.map((plan) => (
              <option key={plan.id} value={plan.id}>
                {plan.name} · {planIntervalLabel(plan)} · {formatMoney(plan.amount, plan.currency)}
              </option>
            ))}
          </select>
        </Field>
        <button className="desk-button-primary" type="submit" disabled={!selectedPlan || start.isPending}>
          {start.isPending ? "Starting…" : "Start term"}
        </button>
      </form>
      {terms.isLoading ? <p className="mt-3 text-sm text-muted">Loading terms…</p> : null}
      {terms.data?.length === 0 ? <p className="mt-3 text-sm text-muted">No terms yet.</p> : null}
      {terms.data?.length ? (
        <ul className="mt-3 divide-y divide-line text-sm">
          {terms.data.map((term) => (
            <li key={term.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-semibold text-ink">{term.plan_name}</p>
                <p className="text-xs text-muted">
                  {new Date(term.starts_at).toLocaleDateString()} – {new Date(term.ends_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={term.status === "active" ? "success" : term.status === "expired" ? "neutral" : "warn"}>
                  {term.status}
                </Badge>
                {term.status === "active" ? (
                  <button className="desk-button" type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(term.id)}>
                    Cancel term
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {terms.isError ? <p className="mt-3 text-sm text-danger" role="alert">{planErrorText(terms.error, "Could not load terms.")}</p> : null}
      {error ? <p className="mt-3 text-sm text-danger" role="alert">{planErrorText(error, "Could not update the term.")}</p> : null}
    </Modal>
  );
}
