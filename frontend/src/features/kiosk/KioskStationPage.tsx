import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import {
  endKioskSession,
  runOnlineCommand,
  startKioskSession,
  takeOperatorLease,
  type KioskBootstrap,
  type KioskLease,
} from "./kioskApi";

// Phase 9b online kiosk shell. The Station PIN opens the channel; a signed-in staff
// operator must then take a lease before any work runs, so every action is attributed
// to a person. Session and lease live in component memory only and are dropped on lock.
// Handover composition (work package + evidence + commands) is the next slice.
export function KioskStationPage() {
  const { slug, stationToken = "" } = useParams();
  const [pin, setPin] = useState("");
  const [session, setSession] = useState<KioskBootstrap | null>(null);
  const [lease, setLease] = useState<KioskLease | null>(null);
  const [payload, setPayload] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function unlock(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    try { setSession(await startKioskSession(stationToken, pin, slug)); setPin(""); }
    catch { setError("The Station PIN is invalid or this kiosk is not enabled."); }
    finally { setPending(false); }
  }

  async function signIn() {
    setError(null);
    try { setLease(await takeOperatorLease(stationToken)); }
    catch { setError("Sign in to the staff console with an account allowed to work this Station."); }
  }

  async function resolve(event: FormEvent) {
    event.preventDefault();
    if (!lease) return;
    setError(null); setResult(null);
    try {
      const response = await runOnlineCommand<{ target: { label?: string; name?: string } }>(
        stationToken, lease.lease_token, "resolve_qr", { payload: payload.trim() },
      );
      setResult(response.result.target.label ?? response.result.target.name ?? "Resolved");
      setPayload("");
    } catch { setError("That QR code is not known here, or your lease no longer allows it."); }
  }

  async function lock() {
    try { await endKioskSession(stationToken); } catch { /* the signed cookie still expires */ }
    setSession(null); setLease(null); setResult(null); setPin("");
  }

  return <main className="desk-shell min-h-screen px-5 py-8" id="main-content" tabIndex={-1}>
    <div className="mx-auto max-w-2xl">
      <SpaceWorksBadge />
      <section className="desk-panel mt-5 p-5" aria-labelledby="kiosk-title">
        <h1 id="kiosk-title" className="title-page">{session ? session.station.name : "Kiosk station"}</h1>
        {!session ? <form className="mt-5 grid gap-3" onSubmit={unlock}>
          <label className="eyebrow" htmlFor="kiosk-station-pin">Station PIN</label>
          <input id="kiosk-station-pin" className="desk-input font-mono text-xl tracking-widest" inputMode="numeric" autoComplete="off" pattern="[0-9]{8}" maxLength={8} required value={pin} onChange={(event) => setPin(event.target.value.replace(/\D/g, ""))} />
          <button className="desk-button-primary" type="submit" disabled={pending || pin.length !== 8}>{pending ? "Unlocking…" : "Unlock station"}</button>
        </form> : <div className="mt-5 grid gap-4">
          <p className="text-sm text-muted">{session.makerspace.name} · {session.station.kind} station</p>
          {!lease ? <button className="desk-button-primary" type="button" onClick={signIn}>Start operator shift</button> : <form className="grid gap-3" onSubmit={resolve}>
            <label className="eyebrow" htmlFor="kiosk-qr-payload">Scan or type a QR code</label>
            <input id="kiosk-qr-payload" className="desk-input font-mono" autoComplete="off" required value={payload} onChange={(event) => setPayload(event.target.value)} />
            <button className="desk-button-primary" type="submit" disabled={!lease.permitted_operations.includes("resolve_qr")}>Look up</button>
            {result ? <p className="text-sm" role="status">{result}</p> : null}
          </form>}
          <button className="desk-button-danger" type="button" onClick={lock}>Lock station</button>
        </div>}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
      </section>
    </div>
  </main>;
}
