import { useState } from "react";
import { staffRequest } from "../../lib/api";
import { evidenceErrorText } from "../staff/evidenceUi";
import type { RecoveryReplay } from "./useKioskReplays";
import { replayGuidance } from "./replayRecoveryGuidance";

export function KioskReplayDetail({ row }: { row: RecoveryReplay }) {
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function preview() {
    setError(null); setUrl(null); setPending(true);
    try { setUrl((await staffRequest<{ url: string }>(`/admin/evidence/${row.evidence_id}`)).url); }
    catch (failure) { setError(evidenceErrorText(failure)); }
    finally { setPending(false); }
  }
  return <div className="grid gap-2 text-sm">
    <p>{row.failure_detail} <span className="font-mono">({row.failure_code})</span></p>
    <p>{replayGuidance(row.failure_code)}</p>
    <p>{row.station_name} · {row.operator_display} · {new Date(row.completed_at).toLocaleString()}</p>
    <p className="break-all">Aggregate {row.aggregate_id} · sequence {row.sequence}</p>
    {row.recovery_request_id ? <p>Request #{row.recovery_request_id}</p> : null}
    {row.recovery_loan_id ? <p>Direct loan #{row.recovery_loan_id}</p> : null}
    {row.predecessor_id ? <p className="break-all">Predecessor {row.predecessor_id} · {row.predecessor_state}</p> : null}
    <p className="text-muted">Recovery retained until at least {new Date(row.retained_until).toLocaleString()}. Evidence has its own retention policy.</p>
    {row.evidence_id && row.can_view_evidence ? <button type="button" className="desk-button-secondary" disabled={pending} onClick={() => { void preview(); }}>{pending ? "Loading evidence…" : "Preview failed evidence"}</button> : null}
    {url ? <a className="desk-button-secondary" href={url} target="_blank" rel="noopener noreferrer">Open failed evidence photo</a> : null}
    {error ? <p role="alert" className="text-danger">{error}</p> : null}
    {row.resolution_code ? <p role="status">Resolved: {row.resolution_code.replace(/_/g, " ")} · {row.resolved_by_display}
      {row.replacement_command_id ? ` · replacement ${row.replacement_command_id}` : ""}</p> : null}
  </div>;
}
