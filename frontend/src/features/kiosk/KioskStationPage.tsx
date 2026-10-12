import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams, useSearchParams } from "react-router-dom";

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
import { useKioskQueue } from "./useKioskQueue";
import { KioskOfflineHandover } from "./KioskOfflineHandover";
import { KioskReplayCorrection } from "./KioskReplayCorrection";

// Only an online-obtained lease and selected package can survive an offline reload.
// Reset destroys encrypted local work; the cookie and human grant remain server-owned.
export function KioskStationPage() {
  const { slug, stationToken = "" } = useParams();
  const [searchParams] = useSearchParams();
  const recoveryId = searchParams.get("recovery");
  const [pin, setPin] = useState("");
  const [session, setSession] = useState<KioskBootstrap | null>(null);
  const [lease, setLease] = useState<KioskLease | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [continuing, setContinuing] = useState(false);
  const [resetRequested, setResetRequested] = useState(false);
  const offline = useKioskQueue(stationToken, slug, recoveryId);
  const activeSession = session ?? offline.queue?.session ?? null;
  const activeLease = lease ?? offline.queue?.lease ?? null;
  const queueMode = Boolean(offline.queue && (!offline.online || offline.restored || continuing));
  const hasCommands = Boolean(offline.queue?.commands.length);

  useEffect(() => {
    if (offline.restored && !offline.queue) { setSession(null); setLease(null); }
  }, [offline.restored, offline.queue]);

  const lock = useCallback(async () => {
    await offline.reset();
    setSession(null); setLease(null); setPin("");
    setContinuing(false); setResetRequested(false);
    try { await endKioskSession(stationToken); } catch { /* the signed cookie still expires */ }
  }, [stationToken, offline.reset]);
  useIdleReset(Boolean(activeSession), activeLease?.expires_at ?? activeSession?.session_expires_at, () => {
    // Idle never discards pending captures silently. Authority expiry is pruned by
    // the store; the UI requests an explicit destructive reset for unexpired work.
    if (hasCommands) setResetRequested(true);
    else void lock().catch(() => setError("Local reset failed. Close this kiosk and reconnect."));
  });

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
        <h1 id="kiosk-title" className="title-page">{activeSession ? activeSession.station.name : "Kiosk station"}</h1>
        {!activeSession && !offline.online ? <p className="mt-5 text-sm" role="status">Reconnect to unlock and load this handover</p> : !activeSession ? <form className="mt-5 grid gap-3" onSubmit={unlock}>
          <label className="eyebrow" htmlFor="kiosk-station-pin">Station PIN</label>
          <input id="kiosk-station-pin" className="desk-input font-mono text-xl tracking-widest" inputMode="numeric" autoComplete="off" pattern="[0-9]{8}" maxLength={8} required value={pin} onChange={(event) => setPin(event.target.value.replace(/\D/g, ""))} />
          <button className="desk-button-primary" type="submit" disabled={pending || pin.length !== 8}>{pending ? "Unlocking…" : "Unlock station"}</button>
        </form> : <div className="mt-5 grid gap-4">
          <p className="text-sm text-muted">{activeSession.makerspace.name} · {activeSession.station.kind} station</p>
          {recoveryId ? <KioskReplayCorrection key={`${stationToken}/${recoveryId}`} id={recoveryId} token={stationToken} session={activeSession} online={offline.online} onQueueChange={offline.setQueue} /> : !activeLease ? <button className="desk-button-primary" type="button" disabled={!offline.online} onClick={signIn}>Start operator shift</button> : queueMode && offline.queue ? <KioskOfflineHandover
            queue={offline.queue} onChange={() => { void offline.refresh(); }} retry={() => { void offline.retry(); }}
            acknowledge={() => { void lock().catch(() => setError("Local reset failed.")); }}
          /> : <>
            {offline.online && !hasCommands ? <KioskOnlineScanner token={stationToken} lease={activeLease} /> : null}
            {activeSession.station.kind === "handover" && offline.online && !hasCommands ? <KioskOnlineHandover token={stationToken} lease={activeLease} makerspaceId={activeSession.makerspace.id}
              onWorkLoaded={(work) => offline.save(activeSession, activeLease, work)} /> : null}
            {!offline.online ? <p className="text-sm" role="status">Reconnect to unlock and load this handover</p> : null}
            {offline.queue ? <button type="button" className="desk-button-secondary" onClick={() => setContinuing(true)}>Continue with encrypted queue</button> : null}
          </>}
          <div className="flex flex-wrap gap-3">
            <button className="desk-button-secondary" type="button" onClick={() => { void enterKioskMode(); }}>Full screen</button>
            <button className="desk-button-danger" type="button" onClick={() => {
              if (hasCommands) setResetRequested(true);
              else void lock().catch(() => setError("Local reset failed."));
            }}>Lock station</button>
          </div>
        </div>}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
        {offline.storageError ? <p className="mt-3 text-sm text-muted" role="status">{offline.storageError}</p> : null}
        {resetRequested ? <section className="mt-4 grid gap-2" aria-label="Confirm local reset">
          <p className="text-sm text-danger">Locking clears this Station's encrypted work and photos, including pending or failed commands.</p>
          <button className="desk-button-danger" type="button" onClick={() => { void lock().catch(() => setError("Local reset failed.")); }}>Discard local work and lock</button>
          <button className="desk-button-secondary" type="button" onClick={() => setResetRequested(false)}>Keep working</button>
        </section> : null}
      </section>
    </div>
  </main>;
}
