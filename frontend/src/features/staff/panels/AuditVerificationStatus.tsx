import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { staffRequest } from "../../../lib/api";

type Coverage = {
  attempt: number;
  chain_status: string;
  anchor_status: string;
  row_count: number;
  mac_valid_count: number;
  unattested_count: number;
  mac_invalid_count: number;
  mac_unavailable_count: number;
  unbatched_count: number;
  local_batch_verified_count: number;
  batch_invalid_count: number;
  batch_unavailable_count: number;
  externally_anchored_count: number;
};
export type VerificationRun = { id: number; state: string; terminal: boolean; coverage: Coverage };
type Accepted = { id: number; state: string; deduplicated: boolean; status_url: string };

const POLL_MS = 3000;

// Trust wording comes from the orthogonal coverage dimensions, never from the run state.
// "Fully verified" needs every row MAC-valid AND in a locally valid batch AND the chain
// valid AND the configured anchor confirming it; anything weaker says so.
export function verificationVerdict(run: VerificationRun): string {
  if (!run.terminal) return "Verification in progress…";
  if (run.state === "FAILED" || run.state === "TIMED_OUT") return "Verification did not complete.";
  const c = run.coverage;
  const invalid = c.mac_invalid_count + c.batch_invalid_count > 0
    || c.chain_status === "invalid" || c.anchor_status === "invalid";
  if (invalid) return "Integrity problems were found in this range.";
  const full = run.state === "SUCCEEDED" && c.row_count > 0 && c.mac_valid_count === c.row_count
    && !c.unattested_count && !c.mac_unavailable_count && !c.unbatched_count && !c.batch_unavailable_count
    && c.local_batch_verified_count === c.row_count && c.chain_status === "locally_verified"
    && c.anchor_status === "externally_anchored" && c.externally_anchored_count === c.row_count;
  return full ? "All entries fully verified." : "No invalid entries found; verification coverage is incomplete.";
}

function gaps(c: Coverage): string[] {
  const out: string[] = [];
  if (c.unattested_count) out.push(`${c.unattested_count} unattested`);
  if (c.mac_unavailable_count) out.push(`${c.mac_unavailable_count} MAC unavailable`);
  if (c.unbatched_count) out.push(`${c.unbatched_count} not yet in a signed batch`);
  if (c.batch_unavailable_count) out.push(`${c.batch_unavailable_count} batch unavailable`);
  if (c.chain_status === "unavailable" || c.chain_status === "pending") out.push("scope chain unavailable");
  if (c.anchor_status === "not_configured") out.push("external anchor not configured");
  if (c.anchor_status === "unavailable") out.push("external anchor unavailable");
  return out;
}

export function AuditVerificationStatus({
  makerspaceId,
  params,
}: {
  makerspaceId: string;
  params: Record<string, string>;
}) {
  const queryClient = useQueryClient();
  const [accepted, setAccepted] = useState<Accepted | null>(null);
  const runId = accepted?.id ?? null;
  const base = `/admin/makerspace/${makerspaceId}/audit-verifications`;
  const start = useMutation({
    mutationFn: () => {
      const { makerspace: _ignored, ...body } = params;
      return staffRequest<Accepted>(base, { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: setAccepted,
  });
  const status = useQuery({
    queryKey: ["audit-verification", makerspaceId, runId],
    // The API returns a versioned relative URL; staffRequest already adds /api/v1.
    queryFn: () => staffRequest<VerificationRun>(accepted!.status_url.replace(/^\/api\/v1(?=\/)/, "")),
    enabled: runId !== null,
    // Poll only while non-terminal; unmounting the panel stops it with the query.
    refetchInterval: (query) => (query.state.data?.terminal ? false : POLL_MS),
  });
  const run = status.data;
  const finished = run?.terminal ?? false;
  useEffect(() => {
    // A finished run appended its own audit row: refresh the explorer list once.
    if (finished) void queryClient.invalidateQueries({ queryKey: ["audit"] });
  }, [finished, runId, queryClient]);
  return (
    <div className="mb-3 rounded-md border border-line bg-bg p-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <button
          className="desk-button-primary"
          type="button"
          disabled={!makerspaceId || start.isPending || (accepted !== null && !run?.terminal)}
          onClick={() => start.mutate()}
        >
          Verify these entries
        </button>
        {!makerspaceId ? <span className="text-muted">Choose one makerspace to verify.</span> : null}
        {accepted && !run ? <span className="text-muted">Loading verification status…</span> : null}
        {run ? <span className="font-medium">{verificationVerdict(run)}</span> : null}
      </div>
      {start.error ? <p className="mt-2 text-danger">{start.error.message}</p> : null}
      {status.error ? (
        <p className="mt-2 text-danger">
          {status.error.message}{" "}
          <button type="button" className="desk-button-ghost" onClick={() => void status.refetch()}>Retry status</button>
        </p>
      ) : null}
      {run?.terminal && gaps(run.coverage).length ? (
        <p className="mt-2 text-muted">Coverage gaps: {gaps(run.coverage).join(", ")}.</p>
      ) : null}
      {run?.terminal ? (
        <p className="mt-1 text-xs text-muted">
          {run.coverage.row_count} rows · {run.coverage.mac_valid_count} MAC-valid ·{" "}
          {run.coverage.local_batch_verified_count} in a verified batch · chain {run.coverage.chain_status} ·
          anchor {run.coverage.anchor_status.replace("_", " ")}
        </p>
      ) : null}
    </div>
  );
}
