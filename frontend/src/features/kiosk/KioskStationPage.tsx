import { useCallback, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { KioskOnlineHandover } from "./KioskOnlineHandover";
import { KioskOnlineScanner } from "./KioskOnlineScanner";
import {
  endKioskSession,
  startKioskSession,
  takeOperatorLease,
  type KioskBootstrap,
  type KioskLease,
} from "./kioskApi";
import { enterKioskMode, useIdleReset } from "./kioskSession";

// Phase 9b online kiosk shell. The Station PIN opens the channel; a signed-in staff
// operator must then take a lease before any work runs, so every action is attributed
// to a person. Session and lease live in component memory only and are dropped on lock,
// idle timeout or expiry. The Station kind selects the scanner or handover shell.
export function KioskStationPage() {
  const { slug, stationToken = "" } = useParams();
  const [pin, setPin] = useState("");
  const [session, setSession] = useState<KioskBootstrap | null>(null);
  const [lease, setLease] = useState<KioskLease | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const lock = useCallback(async () => {
    setSession(null); setLease(null); setPin("");
    try { await endKioskSession(stationToken); } catch { /* the signed cookie still expires */ }
  }, [stationToken]);
  useIdleReset(Boolean(session), lease?.expires_at ?? session?.session_expires_at, () => { void lock(); });

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
          {!lease ? <button className="desk-button-primary" type="button" onClick={signIn}>Start operator shift</button> : <>
            <KioskOnlineScanner token={stationToken} lease={lease} />
            {session.station.kind === "handover" ? <KioskOnlineHandover token={stationToken} lease={lease} makerspaceId={session.makerspace.id} /> : null}
          </>}
          <div className="flex flex-wrap gap-3">
            <button className="desk-button-secondary" type="button" onClick={() => { void enterKioskMode(); }}>Full screen</button>
            <button className="desk-button-danger" type="button" onClick={() => { void lock(); }}>Lock station</button>
          </div>
        </div>}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
      </section>
    </div>
  </main>;
}
