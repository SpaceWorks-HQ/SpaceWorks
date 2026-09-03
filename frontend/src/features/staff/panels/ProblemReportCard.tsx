import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Field } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import type { Makerspace } from "./shared";
import { OUTCOME_OPTIONS, type ProblemReport, type TriageOutcome } from "./AccountabilityTypes";

export function ProblemReportCard({ row, makerspace, onTriaged }: { row: ProblemReport; makerspace: Makerspace; onTriaged: () => void }) {
  const [outcome, setOutcome] = useState<TriageOutcome>("no_issue");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [note, setNote] = useState("");
  const actionable = outcome !== "no_issue";
  const resolutions = actionable
    ? row.items
        .map((item) => ({ item_id: item.id, quantity: Number(quantities[item.id] || 0) }))
        .filter((resolution) => resolution.quantity > 0)
    : [];
  const triage = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspace/${makerspace.id}/problem-reports/${row.id}/triage`, {
      method: "POST",
      body: JSON.stringify({ outcome, resolutions, note }),
    }),
    onSuccess: onTriaged,
  });

  return (
    <div className="grid gap-3 rounded-md border border-line bg-surface p-3 text-sm">
      <div className="min-w-0">
        <p className="font-medium text-ink">{row.label || "(tool)"}</p>
        <p className="font-mono text-xs text-muted">{row.requester_username} | {new Date(row.created_at).toLocaleString()}</p>
        <p className="mt-1 break-words text-ink">{row.note}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {OUTCOME_OPTIONS.map((option) => (
          <label key={option.value} className="flex items-center gap-2 rounded-md border border-line bg-bg px-2 py-1 text-xs text-ink">
            <input type="radio" name={`problem-outcome-${row.id}`} value={option.value} checked={outcome === option.value} onChange={() => setOutcome(option.value)} />
            {option.label}
          </label>
        ))}
      </div>
      {actionable ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {row.items.map((item) => (
            <label key={item.id} className="eyebrow grid gap-1">
              <span>{item.product_name} ({item.issued_quantity})</span>
              <input
                className="desk-input"
                type="number"
                min={0}
                max={item.issued_quantity}
                value={quantities[item.id] ?? ""}
                onChange={(event) => setQuantities((current) => ({ ...current, [item.id]: event.target.value }))}
                placeholder="0"
              />
            </label>
          ))}
        </div>
      ) : null}
      <Field label="Triage note"><textarea className="desk-input min-h-20" value={note} onChange={(event) => setNote(event.target.value)} /></Field>
      <div className="flex flex-wrap items-center justify-between gap-3">
        {triage.error ? <p className="text-sm text-danger">{(triage.error as Error).message}</p> : <span />}
        <button className="desk-button-primary" type="button" disabled={triage.isPending || (actionable && resolutions.length === 0)} onClick={() => triage.mutate()}>
          Save triage
        </button>
      </div>
    </div>
  );
}
