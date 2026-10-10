import { useState, type FormEvent } from "react";
import { CameraCapture } from "../../components/ui/CameraCapture";
import { enqueueCommand } from "./offlineQueueStore";
import { normalizeEvidence } from "./offlineEvidence";
import { registerKioskSync } from "./useKioskQueue";
import type { OfflineQueue } from "./offlineQueueTypes";
import type { ReplayEnvelope } from "./kioskReplayApi";
import { KioskQueueStatus } from "./KioskQueueStatus";

export function KioskOfflineHandover({ queue, onChange, retry, acknowledge }: {
  queue: OfflineQueue; onChange: (queue: OfflineQueue) => void; retry: () => void; acknowledge: () => void;
}) {
  const [selected, setSelected] = useState(queue.works[0]?.id ?? "");
  const [kind, setKind] = useState<ReplayEnvelope["kind"]>("assign_box");
  const [box, setBox] = useState("");
  const [remark, setRemark] = useState("");
  const [assetQrs, setAssetQrs] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [camera, setCamera] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loaded = queue.works.find((item) => item.id === selected);
  const work = loaded?.work;
  const allowed = queue.lease.permitted_operations;
  const choices: ReplayEnvelope["kind"][] = work?.kind === "direct_loan" ? ["direct_return"] : ["assign_box", "reviewed_issue", "reviewed_return"];
  const operation = choices.includes(kind) ? kind : choices[0];
  const returning = operation.endsWith("return");

  async function capture(event: FormEvent) {
    event.preventDefault();
    if (!loaded || !work || busy) return;
    setBusy(true); setError(null);
    try {
      const image = operation === "assign_box" ? undefined : photo ? await normalizeEvidence(photo, work.evidence_max_bytes) : undefined;
      const identity = { version: 1 as const, client_command_id: crypto.randomUUID(), aggregate_id: loaded.aggregateId,
        sequence: 1, client_created_at: new Date().toISOString() };
      const evidence = image ? { evidence_type: returning ? "return" as const : "issue" as const,
        content_type: image.type, size_bytes: image.size } : undefined;
      const payload = operation === "assign_box" ? { request_id: work.id, box_code: box.trim() }
        : operation === "reviewed_issue" ? { request_id: work.id, remark: remark.trim(),
          asset_qr_payloads: assetQrs.split(/\r?\n/).map((value) => value.trim()).filter(Boolean), rejects: [] }
        : operation === "reviewed_return" ? { request_id: work.id, box_code: box.trim(), remark: remark.trim(),
          resolutions: work.lines.map((line) => ({ item_id: line.item_id, returned: Math.max(0, line.quantity - line.returned) })) }
        : { loan_id: work.id, notes: remark.trim(), qr_payload: box.trim(), resolutions:
          work.lines.filter((line) => line.quantity > line.returned).map((line) => ({ item_id: line.item_id, returned: line.quantity - line.returned })) };
      const envelope = { ...identity, kind: operation, payload, ...(evidence ? { evidence } : {}) } as ReplayEnvelope;
      onChange(await enqueueCommand(queue.scope, loaded.id, envelope, image));
      setPhoto(null); setBox(""); setRemark(""); setAssetQrs("");
      void registerKioskSync().catch(() => undefined);
      retry();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Capture failed. Nothing was queued."); }
    finally { setBusy(false); }
  }

  return <div className="grid gap-4">
    <p className="text-sm text-muted">Continue only a loaded handover. Work is Queued until the server confirms it.</p>
    <form className="grid gap-3" onSubmit={capture}>
      <label className="grid gap-1 text-sm">Loaded handover<select className="desk-input" value={selected} disabled={busy} onChange={(event) => { setSelected(event.target.value); setPhoto(null); setBox(""); setRemark(""); }}>
        {queue.works.map((item) => <option key={item.id} value={item.id}>{item.work.display_label}</option>)}
      </select></label>
      <label className="grid gap-1 text-sm">Operation<select className="desk-input" value={operation} disabled={busy} onChange={(event) => { setKind(event.target.value as ReplayEnvelope["kind"]); setPhoto(null); }}>
        {choices.map((choice) => <option key={choice} disabled={!allowed.includes(choice)} value={choice}>{choice.replace(/_/g, " ")}</option>)}
      </select></label>
      {operation === "assign_box" || returning ? <label className="grid gap-1 text-sm">Scan box or return QR<input className="desk-input font-mono" required value={box} disabled={busy} onChange={(event) => setBox(event.target.value)} /></label> : null}
      {operation !== "assign_box" ? <>
        {operation === "reviewed_issue" ? <label className="grid gap-1 text-sm">Asset QRs (one per line)<textarea className="desk-input font-mono" disabled={busy} value={assetQrs} onChange={(event) => setAssetQrs(event.target.value)} /></label> : null}
        <label className="grid gap-1 text-sm">Evidence photo<input key={`${selected}/${operation}/${photo ? "selected" : "empty"}`} type="file" accept="image/*" capture="environment" disabled={busy} onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} /></label>
        {Boolean(navigator.mediaDevices) ? <button type="button" className="desk-button-secondary" disabled={busy} onClick={() => setCamera(true)}>Take evidence photo</button> : null}
        {photo ? <p className="text-sm" role="status">Photo selected; it will be normalized and encrypted with the command.</p> : null}
        <label className="grid gap-1 text-sm">Remark<input className="desk-input" required={returning} disabled={busy} value={remark} onChange={(event) => setRemark(event.target.value)} /></label>
      </> : null}
      <button type="submit" className="desk-button-primary" disabled={busy || !allowed.includes(operation) || (operation !== "assign_box" && !photo)}>{busy ? "Encrypting capture…" : "Queue handover"}</button>
    </form>
    <CameraCapture open={camera} onClose={() => setCamera(false)} onCapture={(file) => { setPhoto(file); setCamera(false); }} label="Handover evidence" />
    {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
    <KioskQueueStatus queue={queue} retry={retry} acknowledge={acknowledge} />
  </div>;
}
