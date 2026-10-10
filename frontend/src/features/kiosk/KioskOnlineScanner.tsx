import { useState, type FormEvent } from "react";

import { runOnlineCommand, type KioskLease } from "./kioskApi";

// Online-only QR lookup. Every call goes through the lease-checked command route; the
// server re-resolves the payload inside the Station's makerspace.
export function KioskOnlineScanner({ token, lease }: { token: string; lease: KioskLease }) {
  const [payload, setPayload] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(event: FormEvent) {
    event.preventDefault();
    setError(null); setResult(null);
    try {
      const response = await runOnlineCommand<{ target: { label?: string; name?: string } }>(
        token, lease.lease_token, "resolve_qr", { payload: payload.trim() },
      );
      setResult(response.result.target.label ?? response.result.target.name ?? "Resolved");
      setPayload("");
    } catch { setError("That QR code is not known here, or your lease no longer allows it."); }
  }

  return <form className="grid gap-3" onSubmit={resolve}>
    <label className="eyebrow" htmlFor="kiosk-qr-payload">Scan or type a QR code</label>
    <input id="kiosk-qr-payload" className="desk-input font-mono" autoComplete="off" required value={payload} onChange={(event) => setPayload(event.target.value)} />
    <button className="desk-button-primary" type="submit" disabled={!lease.permitted_operations.includes("resolve_qr")}>Look up</button>
    {result ? <p className="text-sm" role="status">{result}</p> : null}
    {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
  </form>;
}
