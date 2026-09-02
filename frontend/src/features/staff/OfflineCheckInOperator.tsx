import { useCallback, useEffect, useState } from "react";

import QrScanner from "../../components/ui/QrScanner";
import { StructuredApiError } from "../../lib/api";
import type {
  OfflineRoster,
  OfflineRosterRegistration,
  QueuedCheckIn,
  SyncResponse,
} from "./eventCheckInOfflineApi";
import {
  applySyncResults,
  loadOfflineState,
  pruneExpiredOfflineStates,
  queueOfflineCheckIn,
  saveOfflineRoster,
  wipeOfflineState,
  type OfflineCheckInState,
} from "./eventCheckInOfflineStore";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export function OfflineCheckInOperator({
  scope,
  download,
  synchronize,
  onSynchronized,
  autoDownload = false,
}: {
  scope: string;
  download: () => Promise<OfflineRoster>;
  synchronize: (roster: OfflineRoster, operations: QueuedCheckIn[]) => Promise<SyncResponse>;
  onSynchronized?: () => void | Promise<void>;
  autoDownload?: boolean;
}) {
  const [state, setState] = useState<OfflineCheckInState | null>(null);
  const [resolved, setResolved] = useState<OfflineRosterRegistration | null>(null);
  const [scanning, setScanning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [autoAttempted, setAutoAttempted] = useState(false);

  const refresh = useCallback(async () => {
    await pruneExpiredOfflineStates();
    setState(await loadOfflineState(scope));
  }, [scope]);

  const downloadNow = useCallback(async () => {
    setBusy(true); setError(null);
    try { setState(await saveOfflineRoster(scope, await download())); }
    catch (cause) {
      if (cause instanceof StructuredApiError && [400, 403, 410].includes(cause.status)) {
        await wipeOfflineState(scope); setState(null);
      }
      setError(cause instanceof Error ? cause.message : "Could not download roster.");
    }
    finally { setBusy(false); }
  }, [download, scope]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const visibility = () => { if (!document.hidden) void refresh(); };
    const connection = () => setOnline(navigator.onLine);
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("online", connection);
    window.addEventListener("offline", connection);
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("online", connection);
      window.removeEventListener("offline", connection);
    };
  }, [refresh]);
  useEffect(() => {
    if (autoDownload && !state && !busy && !autoAttempted) {
      setAutoAttempted(true);
      void downloadNow();
    }
  }, [autoAttempted, autoDownload, busy, downloadNow, state]);

  function handleScan(value: string) {
    setScanning(false); setError(null);
    if (!state || Date.now() > Date.parse(state.roster.expires_at)) {
      setError("The offline roster expired. Download it again."); return;
    }
    const match = state.roster.registrations.find(
      (row) => row.checkin_token.toLowerCase() === value.trim().toLowerCase(),
    );
    if (!match) { setError("That is not a check-in code for this event."); return; }
    setResolved(match);
  }

  async function confirm() {
    if (!resolved || !state) return;
    const now = new Date();
    if (now > new Date(state.roster.scan_closes_at)) {
      setError("The event check-in window has closed."); return;
    }
    const operation: QueuedCheckIn = {
      operation_id: crypto.randomUUID(),
      checkin_token: resolved.checkin_token,
      reported_occurred_at: now.toISOString(),
    };
    try {
      setState(await queueOfflineCheckIn(scope, operation));
      setResolved(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not queue attendance.");
    }
  }

  async function syncNow() {
    if (!state?.operations.length) return;
    setBusy(true); setError(null);
    try {
      const response = await synchronize(state.roster, state.operations);
      setState(await applySyncResults(scope, response.results, response.recorded_at));
      await onSynchronized?.();
    } catch (cause) {
      if (cause instanceof StructuredApiError && [400, 403, 410].includes(cause.status)) {
        await wipeOfflineState(scope); setState(null);
      }
      setError(cause instanceof Error ? cause.message : "Could not synchronize check-ins.");
    } finally { setBusy(false); }
  }

  async function wipe() {
    await wipeOfflineState(scope);
    setState(null); setResolved(null); setScanning(false); setError(null);
  }

  return <section className="mt-3 rounded-lg border border-line bg-panel p-3" aria-labelledby={`${scope}-offline-title`}>
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div><h4 id={`${scope}-offline-title`} className="font-semibold text-ink">Offline-ready check-in</h4><p className="text-xs text-muted">{online ? "Online" : "Offline"} · attendee names are encrypted on this device.</p></div>
      <button type="button" className={`desk-button ${FOCUS}`} disabled={busy} onClick={downloadNow}>{state ? "Refresh roster" : "Download roster"}</button>
    </div>
    {state ? <div className="mt-3 grid gap-2 text-sm">
      <p className="text-muted">Expires {new Date(state.roster.expires_at).toLocaleString()} · <strong className="text-ink">{state.operations.length}</strong> queued · Last sync {state.lastSyncedAt ? new Date(state.lastSyncedAt).toLocaleString() : "never"}</p>
      <p className="text-xs text-muted">Keep this page open while disconnected. Closing or reloading cannot reopen it offline in this release.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={`desk-button-primary ${FOCUS}`} onClick={() => setScanning(true)}>Scan offline</button>
        <button type="button" className={`desk-button ${FOCUS}`} disabled={!online || busy || !state.operations.length} onClick={syncNow}>Synchronize</button>
        <button type="button" className={`desk-button-danger ${FOCUS}`} onClick={wipe}>Wipe attendee data</button>
      </div>
      <p aria-live="polite" className="sr-only">{state.operations.length} queued check-ins. {state.conflicts.length} conflicts.</p>
      {state.conflicts.length ? <div role="alert" className="rounded-md border border-warning bg-warning-soft p-2 text-warning-ink"><strong>{state.conflicts.length} synchronization conflicts</strong><ul className="mt-1 list-disc pl-5">{state.conflicts.map((item) => <li key={item.operation_id}>{item.outcome.replace(/_/g, " ")}</li>)}</ul></div> : null}
    </div> : <p className="mt-3 text-sm text-muted">No attendee data is stored on this device.</p>}
    {resolved ? <div className="mt-3 rounded-md border border-line p-3"><p className="font-medium text-ink">{resolved.name}</p><p className="text-sm text-muted">Waiver: {resolved.host_waiver_state.replace(/_/g, " ")}</p><div className="mt-2 flex gap-2"><button className={`desk-button-primary ${FOCUS}`} type="button" onClick={confirm}>Confirm attendance</button><button className={`desk-button ${FOCUS}`} type="button" onClick={() => setResolved(null)}>Cancel</button></div></div> : null}
    {error ? <p className="mt-3 text-sm text-danger" role="alert">{error}</p> : null}
    {scanning ? <QrScanner onScan={handleScan} onClose={() => setScanning(false)} /> : null}
  </section>;
}
