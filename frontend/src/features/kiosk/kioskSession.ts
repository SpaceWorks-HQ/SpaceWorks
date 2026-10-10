// In-memory kiosk session helpers. Nothing here touches localStorage/IndexedDB: the
// Station cookie is HttpOnly and the lease token lives only in React state, so a reload
// or idle reset drops all operator authority. Fullscreen and wake lock are usability
// controls only; they grant nothing.
import { useEffect, useRef } from "react";

export const KIOSK_IDLE_RESET_MS = 5 * 60 * 1000;
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "touchstart"] as const;

/** True once `expiresAt` (ISO) is within `skewMs` of now, or unparsable. */
export function isExpired(expiresAt: string | null | undefined, now = Date.now(), skewMs = 5000) {
  if (!expiresAt) return true;
  const at = Date.parse(expiresAt);
  return Number.isNaN(at) || at - skewMs <= now;
}

/** Milliseconds until the earlier of the idle limit and the server expiry. */
export function resetDelay(expiresAt: string | null | undefined, now = Date.now(), idleMs = KIOSK_IDLE_RESET_MS) {
  if (!expiresAt) return idleMs;
  const at = Date.parse(expiresAt);
  return Number.isNaN(at) ? 0 : Math.max(0, Math.min(idleMs, at - now));
}

/** Call `onReset` after inactivity, or when the session/lease expiry passes. */
export function useIdleReset(active: boolean, expiresAt: string | null | undefined, onReset: () => void) {
  const callback = useRef(onReset);
  useEffect(() => { callback.current = onReset; }, [onReset]);
  useEffect(() => {
    if (!active) return undefined;
    let timer = window.setTimeout(() => callback.current(), resetDelay(expiresAt));
    const bump = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => callback.current(), resetDelay(expiresAt));
    };
    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, bump));
    return () => {
      window.clearTimeout(timer);
      ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, bump));
    };
  }, [active, expiresAt]);
}

/** Best-effort fullscreen + screen wake lock; failures are silently ignored. */
export async function enterKioskMode() {
  try { await document.documentElement.requestFullscreen?.(); } catch { /* not allowed */ }
  try {
    const wakeLock = (navigator as Navigator & { wakeLock?: { request: (type: "screen") => Promise<unknown> } }).wakeLock;
    await wakeLock?.request("screen");
  } catch { /* unsupported */ }
}
