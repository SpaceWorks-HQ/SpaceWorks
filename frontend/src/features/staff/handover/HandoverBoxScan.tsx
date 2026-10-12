import { useState } from "react";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";

export function HandoverBoxScan({ code, onCode, makerspaceId }: { code: string; onCode: (code: string) => void; makerspaceId: number }) {
  const [input, setInput] = useState("");
  const [scanner, setScanner] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function scan(payload: string) {
    setBusy(true); setError(""); onCode("");
    try {
      const result = await staffRequest<{ qr: { makerspace: number }; target: { type: string; code?: string } }>("/admin/qr/resolve", { method: "POST", body: JSON.stringify({ payload: payload.trim() }) });
      if (result.qr?.makerspace !== makerspaceId) throw new Error("Scan a container from this makerspace.");
      if (result.target.type !== "box" || !result.target.code) throw new Error("Scan a box/container QR.");
      onCode(result.target.code); setScanner(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not check the box QR."); }
    finally { setBusy(false); }
  }
  return <div className="grid gap-3">
    <p>Scan the container for this handover.</p>
    <button className="desk-button-primary" type="button" disabled={busy} onClick={() => setScanner(true)}>Scan box QR</button>
    <label>Box QR payload<input className="desk-input block w-full" disabled={busy} value={input} onChange={event => { setInput(event.target.value); onCode(""); }} /></label>
    <button className="desk-button" type="button" disabled={busy || !input.trim()} onClick={() => void scan(input)}>Check box QR</button>
    {code ? <p role="status">Verified box: {code}</p> : null}
    {error ? <p role="alert" className="text-danger">{error}</p> : null}
    {scanner ? <QrScanner feedback={error ? <p role="alert">{error}</p> : busy ? <p role="status">Checking container…</p> : null} onScan={payload => { if (!busy) void scan(payload); }} onClose={() => setScanner(false)} /> : null}
  </div>;
}
