import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field, Modal } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews } from "../queryInvalidation";
import { Panel, type Makerspace, useStaffGet } from "./shared";

type Offender = {
  requester_id: number;
  username: string;
  access_status: string;
  restriction_reason: string;
  damaged: number;
  missing: number;
  total_issues: number;
  total_quantity: number;
};
type Overdue = {
  type: "request" | "direct";
  reference_id: number;
  requester_username: string;
  label: string;
  due_at: string;
  days_overdue: number;
};
type Restriction = { requester_id: number; username: string; access_status: string; restriction_reason: string };
type ProblemReportItem = { id: number; product_name: string; issued_quantity: number; tracking_mode: string };
type ProblemReport = { id: number; requester_username: string; label: string; note: string; created_at: string; items: ProblemReportItem[] };
type AccountabilityResponse = {
  repeat_offenders: Offender[];
  overdue: Overdue[];
  restrictions: Restriction[];
  problem_reports: ProblemReport[];
  truncated: { repeat_offenders: boolean; overdue: boolean; problem_reports: boolean };
};
type TriageOutcome = "no_issue" | "damaged" | "missing" | "needs_fix";

const OUTCOME_OPTIONS: Array<{ value: TriageOutcome; label: string }> = [
  { value: "no_issue", label: "No issue" },
  { value: "damaged", label: "Damaged" },
  { value: "missing", label: "Missing" },
  { value: "needs_fix", label: "Needs fix" },
];

export function AccountabilityPanel({ makerspace, isSuperadmin }: { makerspace: Makerspace; isSuperadmin: boolean }) {
  const queryClient = useQueryClient();
  const restrictionFormId = useId();
  const [restrictionTarget, setRestrictionTarget] = useState<Pick<Offender, "requester_id" | "username"> | null>(null);
  const [restrictionReason, setRestrictionReason] = useState("");
  const report = useStaffGet<AccountabilityResponse>(["accountability", makerspace.id], `/admin/makerspace/${makerspace.id}/accountability`);
  const data = report.data;

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["accountability", makerspace.id] });
  };
  const refreshAfterTriage = () => {
    refresh();
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
    queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
  };
  const restrict = useMutation({
    mutationFn: ({ userId, reason }: { userId: number; reason: string }) =>
      staffRequest(`/admin/users/${userId}/restrict`, {
        method: "POST",
        body: JSON.stringify({ status: "restricted", reason }),
      }),
    onSuccess: refresh,
  });
  const restore = useMutation({
    mutationFn: (userId: number) => staffRequest(`/admin/users/${userId}/restore-access`, { method: "POST" }),
    onSuccess: refresh,
  });
  const closeRestrictionDialog = () => {
    setRestrictionTarget(null);
    setRestrictionReason("");
  };
  const submitRestriction = (event: FormEvent) => {
    event.preventDefault();
    const target = restrictionTarget;
    const reason = restrictionReason.trim();
    closeRestrictionDialog();
    if (target && reason) restrict.mutate({ userId: target.requester_id, reason });
  };

  return (
    <div className="grid gap-4">
      {report.isLoading ? <p className="text-sm text-muted">Loading accountability...</p> : null}
      {report.error ? <p className="text-sm text-danger">{(report.error as Error).message}</p> : null}

      <Panel title="Overdue loans">
        {!data?.overdue.length ? (
          <p className="text-sm text-muted">No overdue loans.</p>
        ) : (
          <div className="grid gap-2">
            {data.overdue.map((row) => (
              <div key={`${row.type}-${row.reference_id}`} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface p-2 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-ink">{row.label || "(unnamed)"}</p>
                  <p className="text-xs text-muted">{row.requester_username} | {row.type === "direct" ? "direct handout" : "request"}</p>
                </div>
                <span className="status-box status-box-danger">{row.days_overdue}d overdue</span>
              </div>
            ))}
            {data.truncated.overdue ? <p className="text-xs text-muted">Showing the earliest overdue loans only.</p> : null}
          </div>
        )}
      </Panel>

      <Panel title="Reported problems">
        {!data?.problem_reports.length ? (
          <p className="text-sm text-muted">No open problem reports from public returns.</p>
        ) : (
          <div className="grid gap-3">
            {data.problem_reports.map((row) => (
              <ProblemReportCard key={row.id} row={row} makerspace={makerspace} onTriaged={refreshAfterTriage} />
            ))}
            {data.truncated.problem_reports ? <p className="text-xs text-muted">Showing the oldest open reports only.</p> : null}
          </div>
        )}
      </Panel>

      <Panel title="Repeat offenders">
        {!data?.repeat_offenders.length ? (
          <p className="text-sm text-muted">No damage or loss on record.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-muted">
                  <th scope="col" className="p-2">Requester</th>
                  <th scope="col" className="p-2">Damaged</th>
                  <th scope="col" className="p-2">Missing</th>
                  <th scope="col" className="p-2">Total issues</th>
                  <th scope="col" className="p-2">Status</th>
                  {isSuperadmin ? <th scope="col" className="p-2">Action</th> : null}
                </tr>
              </thead>
              <tbody>
                {data.repeat_offenders.map((row) => (
                  <tr key={row.requester_id} className="border-t border-line">
                    <td className="p-2 font-medium text-ink">{row.username}</td>
                    <td className="p-2 font-mono">{row.damaged}</td>
                    <td className="p-2 font-mono">{row.missing}</td>
                    <td className="p-2 font-mono">{row.total_issues} ({row.total_quantity} units)</td>
                    <td className="p-2 capitalize">{row.access_status}</td>
                    {isSuperadmin ? (
                      <td className="p-2">
                        {row.access_status === "active" ? (
                          <button
                            className="desk-button-danger"
                            type="button"
                            disabled={restrict.isPending}
                            onClick={() => setRestrictionTarget({ requester_id: row.requester_id, username: row.username })}
                          >
                            Restrict
                          </button>
                        ) : (
                          <button className="desk-button-success" type="button" disabled={restore.isPending} onClick={() => restore.mutate(row.requester_id)}>
                            Restore
                          </button>
                        )}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
            {data.truncated.repeat_offenders ? <p className="mt-2 text-xs text-muted">Showing the top offenders only.</p> : null}
          </div>
        )}
      </Panel>

      <Panel title="Restricted requesters">
        {!data?.restrictions.length ? (
          <p className="text-sm text-muted">No restricted requesters with accountability records here.</p>
        ) : (
          <div className="grid gap-2">
            {data.restrictions.map((row) => (
              <div key={row.requester_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line bg-surface p-2 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-ink">{row.username} <span className="text-xs capitalize text-muted">({row.access_status})</span></p>
                  {row.restriction_reason ? <p className="text-xs text-muted">{row.restriction_reason}</p> : null}
                </div>
                {isSuperadmin ? (
                  <button className="desk-button-success" type="button" disabled={restore.isPending} onClick={() => restore.mutate(row.requester_id)}>
                    Restore access
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Panel>
      {restrict.error ? <p className="text-sm text-danger">{(restrict.error as Error).message}</p> : null}
      {restore.error ? <p className="text-sm text-danger">{(restore.error as Error).message}</p> : null}
      <Modal
        open={restrictionTarget !== null}
        onClose={closeRestrictionDialog}
        title="Restrict requester?"
        footer={(
          <div className="desk-actions flex flex-wrap justify-end gap-2">
            <button className="desk-button-secondary" type="button" onClick={closeRestrictionDialog}>Cancel</button>
            {/* Submit no-ops on a blank reason, so leaving it enabled renders a dead button that
                reports nothing. Disabling states the requirement instead of failing silently. */}
            <button className="desk-button-danger" type="submit" form={restrictionFormId} disabled={!restrictionReason.trim() || restrict.isPending}>
              {restrict.isPending ? "Restricting..." : "Restrict requester"}
            </button>
          </div>
        )}
      >
        <form id={restrictionFormId} className="grid gap-3" onSubmit={submitRestriction}>
          <p className="text-sm text-muted">
            Restrict {restrictionTarget?.username ?? "this requester"} from making new requests.
          </p>
          <label className="eyebrow grid gap-2">
            <span>Reason for restriction</span>
            <textarea
              className="desk-input min-h-24"
              required
              value={restrictionReason}
              onChange={(event) => setRestrictionReason(event.target.value)}
            />
          </label>
        </form>
      </Modal>
    </div>
  );
}

function ProblemReportCard({ row, makerspace, onTriaged }: { row: ProblemReport; makerspace: Makerspace; onTriaged: () => void }) {
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
