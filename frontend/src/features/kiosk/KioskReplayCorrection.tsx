import { useEffect, useState, type FormEvent } from "react";
import { staffRequest } from "../../lib/api";
import type { KioskBootstrap } from "./kioskApi";
import type { OfflineQueue } from "./offlineQueueTypes";
import { recoveryPath, type RecoveryReplay } from "./useKioskReplays";
import { listQueues, loadQueue } from "./offlineQueueStore";
import { replayQueue } from "./kioskReplayClient";
import { captureCorrection, loadCorrectiveWork } from "./replayCorrectionCapture";
import { KioskReplayDetail } from "./KioskReplayDetail";
import { replayGuidance } from "./replayRecoveryGuidance";

// Mounted only for ?recovery=<uuid>; ordinary kiosk flows need no query provider.
export function KioskReplayCorrection({ id, token, session, online, onQueueChange }: {
  id: string; token: string; session: KioskBootstrap; online: boolean; onQueueChange: (queue: OfflineQueue) => void;
}) {
  const [row, setRow] = useState<RecoveryReplay | null>(null);
  const [queue, setQueue] = useState<OfflineQueue | null>(null);
  const [box, setBox] = useState("");
  const [remark, setRemark] = useState("");
  const [assetQrs, setAssetQrs] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkReady, setLinkReady] = useState(false);

  useEffect(() => {
    let active = true;
    if (!online) return;
    void staffRequest<RecoveryReplay>(recoveryPath(id)).then((value) => { if (active) setRow(value); })
      .catch(() => { if (active) setError("Sign in with current handover permission to inspect this failure."); });
    void listQueues().then((states) => {
      const saved = states.find((state) => state.token === token && state.commands.some((cmd) => cmd.recoveryReplayId === id));
      if (active && saved) { setQueue(saved); onQueueChange(saved); }
    }).catch(() => undefined);
    return () => { active = false; };
  }, [id, token, online, onQueueChange]);

  const command = queue?.commands.find((item) => item.recoveryReplayId === id);
  const publishQueue = (current: OfflineQueue | null) => {
    setQueue(current);
    // The Station idle/reset contract must see newly queued corrections too.
    // Do not replace its prior failed scope with an empty new corrective shift.
    if (current?.commands.length) onQueueChange(current);
  };
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(null);
    try { await task(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Correction was refused. The original remains unresolved."); }
    finally { setBusy(false); }
  }
  async function replayAndReview(scope: string) {
    await replayQueue(scope);
    const current = await loadQueue(scope);
    publishQueue(current);
    const result = current?.commands.find((item) => item.recoveryReplayId === id)?.result;
    if (result?.state === "succeeded") setLinkReady(true);
  }
  async function capture(event: FormEvent) {
    event.preventDefault();
    if (!row || !queue || busy || command) return;
    await run(async () => {
      const saved = await captureCorrection(queue, row, { box, remark, assetQrs, photo });
      publishQueue(saved); setPhoto(null);
      await replayAndReview(saved.scope);
    });
  }

  return <section className="grid gap-3" aria-label="Failed handover recovery">
    <h2 className="title-section">Failed handover recovery</h2>
    {!online ? <p role="status">Reconnect to review and correct. Original failed evidence stays retained.</p> : !row ? <p role="status">Loading retained failure…</p> : <>
      <KioskReplayDetail key={row.id} row={row} />
      {!row.resolution_code ? <>
        <p className="text-sm">Acknowledge only after verifying no physical change. Review records no inventory change.</p>
        <Acknowledge onConfirm={() => { void run(async () => { setRow(await staffRequest<RecoveryReplay>(`${recoveryPath(id)}resolve/`, {
          method: "POST", body: JSON.stringify({ resolution_code: "acknowledged_no_change" }),
        })); }); }} disabled={busy} />
        {!queue ? <button type="button" className="desk-button-primary" disabled={busy || !row.recovery_request_id && !row.recovery_loan_id}
          onClick={() => { void run(async () => { setQueue(await loadCorrectiveWork(token, session, row)); }); }}>Start corrective shift and load current work</button> : !command ? <form className="grid gap-2" onSubmit={(event) => { void capture(event); }}>
          <p className="text-sm">Current work: {queue.works[0].work.display_label} · {queue.works[0].work.status}. Return corrections record all outstanding items as returned; damage/loss needs the staff return workflow.</p>
          {row.operation_kind === "assign_box" || row.operation_kind.endsWith("return") ? <label className="text-sm">Current box or return QR<input className="desk-input" required value={box} onChange={(event) => setBox(event.target.value)} /></label> : null}
          {row.operation_kind !== "assign_box" ? <>
            <label className="text-sm">New correction photo<input type="file" accept="image/*" required onChange={(event) => setPhoto(event.target.files?.[0] ?? null)} /></label>
            <label className="text-sm">Correction remark<input className="desk-input" required={row.operation_kind.endsWith("return")} value={remark} onChange={(event) => setRemark(event.target.value)} /></label>
            {row.operation_kind === "reviewed_issue" ? <label className="text-sm">Current asset QRs (one per line)<textarea className="desk-input" value={assetQrs} onChange={(event) => setAssetQrs(event.target.value)} /></label> : null}
          </> : null}
          <button className="desk-button-primary" type="submit" disabled={busy}>Capture fresh correction</button>
        </form> : <div className="grid gap-2 text-sm">
          <p role="status">Correction {command.status}. {command.lastFailure ? replayGuidance(command.lastFailure) : ""}</p>
          <button type="button" className="desk-button-secondary" disabled={busy} onClick={() => { void run(() => replayAndReview(queue.scope)); }}>Check corrective replay</button>
          {linkReady || command.result?.state === "succeeded" ? <button type="button" className="desk-button-primary" disabled={busy} onClick={() => { void run(async () => {
            setRow(await staffRequest<RecoveryReplay>(`${recoveryPath(id)}resolve/`, { method: "POST",
              body: JSON.stringify({ resolution_code: "replaced_online", replacement_command_id: command.result?.replay_id }) }));
          }); }}>Link successful correction</button> : null}
        </div>}
      </> : null}
    </>}
    {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
  </section>;
}

function Acknowledge({ onConfirm, disabled }: { onConfirm: () => void; disabled: boolean }) {
  const [confirm, setConfirm] = useState(false);
  return confirm ? <div className="grid gap-2">
    <p>Confirm you inspected the failed handover and verified no physical change occurred.</p>
    <button type="button" className="desk-button-primary" disabled={disabled} onClick={onConfirm}>Record no-change review</button>
    <button type="button" className="desk-button-secondary" disabled={disabled} onClick={() => setConfirm(false)}>Cancel review</button>
  </div> : <button type="button" className="desk-button-secondary" onClick={() => setConfirm(true)}>Acknowledge — no change occurred</button>;
}
