import { useState, type FormEvent } from "react";

import { EvidenceUpload } from "../staff/panels/EvidenceUpload";
import {
  loadWorkPackage,
  prepareEvidence,
  runOnlineCommand,
  type KioskLease,
  type KioskWorkPackage,
} from "./kioskApi";

type Props = { token: string; lease: KioskLease; makerspaceId: number };

// Online reviewed-request handover: load the minimal work package, then assign a box,
// issue or return through the lease-checked command route. Evidence goes straight to
// object storage via the kiosk presign; the server promotes it inside the workflow.
export function KioskOnlineHandover({ token, lease, makerspaceId }: Props) {
  const [requestId, setRequestId] = useState("");
  const [work, setWork] = useState<KioskWorkPackage | null>(null);
  const [boxCode, setBoxCode] = useState("");
  const [remark, setRemark] = useState("");
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = new Set(lease.permitted_operations);
  const presign = (body: object) => prepareEvidence(token, lease.lease_token, body);

  async function load(id: number) {
    setError(null);
    try { setWork(await loadWorkPackage(token, lease.lease_token, "reviewed_request", id)); }
    catch { setWork(null); setError("That request is not available to this Station."); }
  }

  function submitLoad(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    void load(Number(requestId));
  }

  async function run(kind: string, payload: object, done: string) {
    if (!work) return;
    setError(null);
    try {
      await runOnlineCommand(token, lease.lease_token, kind, { request_id: work.id, ...payload });
      setMessage(done); setRemark(""); setBoxCode(""); setEvidenceId(null);
      await load(work.id);
    } catch { setError("The handover was refused. Check the box, photo and remark, then try again."); }
  }

  const resolutions = (work?.lines ?? []).map((line) => ({
    item_id: line.item_id, returned: Math.max(0, line.quantity - line.returned),
  }));
  const canIssue = work?.status === "accepted" && Boolean(work.box) && allowed.has("reviewed_issue");
  const canReturn = (work?.status === "issued" || work?.status === "partially_returned") && allowed.has("reviewed_return");

  return <div className="grid gap-4">
    <form className="flex flex-wrap items-end gap-3" onSubmit={submitLoad}>
      <label className="grid gap-1 text-sm">Request number<input className="desk-input font-mono" inputMode="numeric" required value={requestId} onChange={(event) => setRequestId(event.target.value.replace(/\D/g, ""))} /></label>
      <button className="desk-button-secondary" type="submit" disabled={!requestId}>Load request</button>
    </form>
    {work ? <section className="grid gap-3" aria-label={work.display_label}>
      <p className="text-sm"><strong>{work.display_label}</strong> · {work.person_display || "Requester"} · {work.status}{work.box ? ` · box ${work.box}` : ""}</p>
      <ul className="text-sm">{work.lines.map((line) => <li key={line.item_id}>{line.label} × {line.quantity} (returned {line.returned})</li>)}</ul>
      {work.status === "accepted" && !work.box && allowed.has("assign_box") ? <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); void run("assign_box", { box_code: boxCode.trim() }, "Box assigned."); }}>
        <label className="grid gap-1 text-sm">Box code<input className="desk-input font-mono" required value={boxCode} onChange={(event) => setBoxCode(event.target.value)} /></label>
        <button className="desk-button-primary" type="submit">Assign box</button>
      </form> : null}
      {canIssue || canReturn ? <form className="grid gap-3" onSubmit={(event) => {
        event.preventDefault();
        if (evidenceId === null) return;
        if (canIssue) void run("reviewed_issue", { evidence_id: evidenceId, remark, asset_qr_payloads: [], rejects: [] }, "Issued.");
        else void run("reviewed_return", { evidence_id: evidenceId, remark, box_code: boxCode.trim(), resolutions }, "Returned.");
      }}>
        <EvidenceUpload makerspaceId={makerspaceId} evidenceType={canIssue ? "issue" : "return"} label={canIssue ? "Issue photo" : "Return photo"} presign={presign} onUploaded={setEvidenceId} />
        {canReturn ? <label className="grid gap-1 text-sm">Scan the box<input className="desk-input font-mono" required value={boxCode} onChange={(event) => setBoxCode(event.target.value)} /></label> : null}
        <label className="grid gap-1 text-sm">Remark<input className="desk-input" required={canReturn} value={remark} onChange={(event) => setRemark(event.target.value)} /></label>
        <button className="desk-button-primary" type="submit" disabled={evidenceId === null}>{canIssue ? "Issue items" : "Return all items"}</button>
      </form> : null}
    </section> : null}
    {message ? <p className="text-sm" role="status">{message}</p> : null}
    {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
  </div>;
}
