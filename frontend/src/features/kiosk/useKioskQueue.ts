import { useCallback, useEffect, useRef, useState } from "react";
import { API_V1_URL } from "../../lib/api";
import type { KioskBootstrap, KioskLease, KioskWorkPackage } from "./kioskApi";
import type { OfflineQueue } from "./offlineQueueTypes";
import { listQueues, loadQueue, saveWorkPackage, wipeQueue } from "./offlineQueueStore";
import { replayQueue } from "./kioskReplayClient";

export async function registerKioskSync() {
  if (!("serviceWorker" in navigator)) return;
  // ready can remain pending forever on a dev page without a worker.
  const registration = await navigator.serviceWorker.getRegistration();
  const sync = (registration as ServiceWorkerRegistration & {
    sync?: { register: (tag: string) => Promise<void> };
  } | undefined)?.sync;
  await sync?.register("spaceworks-kiosk-replay");
}

export function useKioskQueue(token: string, slug?: string, recoveryId?: string | null) {
  const [queue, setQueue] = useState<OfflineQueue | null>(null);
  const [online, setOnline] = useState(false);
  const [storageError, setStorageError] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const generation = useRef(0);
  const scope = queue?.scope;
  const apiBase = queue?.apiBase ?? API_V1_URL;

  useEffect(() => {
    generation.current += 1;
    let active = true;
    setQueue(null); setRestored(false);
    void listQueues().then((queues) => {
      const selected = queues.filter((item) => item.token === token && (!slug || item.session.makerspace.slug === slug)
        && (!recoveryId || item.commands.some((command) => command.recoveryReplayId === recoveryId)));
      // Never choose between two human shifts implicitly.
      if (active && selected.length === 1) { setQueue(selected[0]); setRestored(true); }
    }).catch(() => { if (active) setStorageError("Encrypted offline storage is unavailable. Continue online."); });
    return () => { active = false; };
  }, [token, slug, recoveryId]);

  const refresh = useCallback(async () => {
    if (scope) {
      const active = generation.current;
      const state = await loadQueue(scope);
      if (generation.current !== active) return;
      setQueue(state);
      if (!state) setRestored(true); // expired/revoked cached authority also drops memory grants
    }
  }, [scope]);
  const retry = useCallback(async () => {
    if (!scope) return;
    try { await replayQueue(scope); await refresh(); }
    catch { setStorageError("Replay could not start. Retry after reconnecting."); }
  }, [scope, refresh]);

  useEffect(() => {
    let active = true;
    const probe = async () => {
      try {
        // A browser can report onLine=true during a real outage. This existing
        // public endpoint confirms reachability only; it never grants authority.
        const response = await fetch(`${apiBase}/health/`, { credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(5000) });
        if (active) setOnline(response.ok);
      } catch { if (active) setOnline(false); }
    };
    const hint = () => { void probe(); void retry(); };
    window.addEventListener("online", hint); window.addEventListener("offline", hint);
    // Reachability is established by fetch, never by the online hint alone.
    const timer = window.setInterval(hint, 15_000);
    const poll = scope ? window.setInterval(() => { void refresh().catch(() => undefined); }, 2000) : undefined;
    hint();
    return () => {
      active = false;
      window.removeEventListener("online", hint); window.removeEventListener("offline", hint);
      window.clearInterval(timer); window.clearInterval(poll);
    };
  }, [retry, refresh, scope, apiBase]);

  const save = useCallback(async (session: KioskBootstrap, lease: KioskLease, work: KioskWorkPackage) => {
    const active = generation.current;
    try {
      const saved = await saveWorkPackage(token, API_V1_URL, session, lease, work);
      if (generation.current !== active) { await wipeQueue(saved.scope); return; }
      setQueue(saved); setStorageError(null);
    } catch (error) {
      setStorageError(error instanceof Error ? error.message : "Offline preparation failed. Continue online.");
    }
  }, [token]);

  const reset = useCallback(async () => {
    generation.current += 1;
    if (typeof indexedDB === "undefined" || !navigator.locks) {
      if (queue) throw new Error("Offline storage cannot be cleared. Reconnect on this browser.");
      setQueue(null); setRestored(false); return;
    }
    // All cached shifts on this path are discarded explicitly, including a scope
    // not restored because multiple shifts existed. Other Stations are untouched.
    const states = await listQueues();
    for (const state of states.filter((item) => item.token === token)) await wipeQueue(state.scope);
    setQueue(null); setRestored(false);
  }, [token, queue]);

  return { queue, setQueue, online, storageError, restored, save, refresh, retry, reset };
}
