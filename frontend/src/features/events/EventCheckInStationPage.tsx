import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import {
  downloadStationRoster,
  endStationSession,
  startStationSession,
  syncStationRoster,
} from "../staff/eventCheckInOfflineApi";
import { wipeOfflineState } from "../staff/eventCheckInOfflineStore";
import { OfflineCheckInOperator } from "../staff/OfflineCheckInOperator";

export function EventCheckInStationPage() {
  const { stationToken = "" } = useParams();
  const scope = `station:${stationToken}`;
  const [pin, setPin] = useState("");
  const [active, setActive] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    try { await startStationSession(stationToken, pin); setPin(""); setActive(true); }
    catch { setError("The station credential is invalid or outside its event window."); }
    finally { setPending(false); }
  }

  async function exit() {
    await wipeOfflineState(scope);
    try { await endStationSession(stationToken); } catch { /* cookie still expires server-bound */ }
    setActive(false); setPin("");
  }

  return <main className="desk-shell min-h-screen px-5 py-8" id="main-content" tabIndex={-1}>
    <div className="mx-auto max-w-2xl">
      <SpaceWorksBadge />
      <section className="desk-panel mt-5 p-5" aria-labelledby="station-title">
        <h1 id="station-title" className="title-page">Event check-in station</h1>
        {!active ? <form className="mt-5 grid gap-3" onSubmit={submit}>
          <p className="text-sm text-muted">Enter the eight-digit PIN provided by the event organizer.</p>
          <label className="eyebrow" htmlFor="event-station-pin">Station PIN</label>
          <input id="event-station-pin" className="desk-input font-mono text-xl tracking-widest" inputMode="numeric" autoComplete="off" pattern="[0-9]{8}" maxLength={8} required value={pin} onChange={(event) => setPin(event.target.value.replace(/\D/g, ""))} />
          <button className="desk-button-primary" type="submit" disabled={pending || pin.length !== 8}>{pending ? "Unlocking…" : "Unlock station"}</button>
        </form> : <>
          <OfflineCheckInOperator scope={scope} autoDownload download={() => downloadStationRoster(stationToken)} synchronize={(roster, operations) => syncStationRoster(stationToken, roster, operations)} />
          <button className="desk-button-danger mt-4" type="button" onClick={exit}>Wipe data and lock station</button>
        </>}
        {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
      </section>
    </div>
  </main>;
}
