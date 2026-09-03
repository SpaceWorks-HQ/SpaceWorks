import { useId, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Modal } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews } from "../queryInvalidation";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import type { AccountabilityResponse, Offender } from "./AccountabilityTypes";
import { ProblemReportCard } from "./ProblemReportCard";

export function AccountabilityPanel({ makerspace, isSuperadmin }: { makerspace: Makerspace; isSuperadmin: boolean }) {
  const queryClient = useQueryClient();
  const restrictionFormId = useId();
  const [restrictionTarget, setRestrictionTarget] = useState<Pick<Offender, "requester_id" | "username"> | null>(null);
  const [restrictionReason, setRestrictionReason] = useState("");
  const report = useStaffGet<AccountabilityResponse>(["accountability", makerspace.id], `/admin/makerspace/${makerspace.id}/accountability`);
  const data = report.data;
  const anonymous = data?.anonymous_accountability;

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
        {anonymous && anonymous.total_issues > 0 ? (
          <div className="mb-4 rounded-xl border border-warn bg-warn/10 px-3 py-2">
            <p className="text-sm font-medium text-ink">
              Account-less loans: {anonymous.total_issues}{" "}
              {anonymous.total_issues === 1 ? "incident" : "incidents"} ({anonymous.total_quantity}{" "}
              {anonymous.total_quantity === 1 ? "item" : "items"})
            </p>
            <p className="mt-1 text-xs text-muted">
              {anonymous.damaged} damaged, {anonymous.missing} missing. These have no person to
              rank or restrict, so they are reported as a total rather than as a row above.
            </p>
          </div>
        ) : null}
        {!data?.repeat_offenders.length ? (
          <p className="text-sm text-muted">
            {anonymous && anonymous.total_issues > 0
              ? "No damage or loss recorded against a named person."
              : "No damage or loss on record."}
          </p>
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
