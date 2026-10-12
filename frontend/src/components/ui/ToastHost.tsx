import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { dismissToast, toastStore, undoToast } from "./toastStore";

export function ToastHost() {
  const rows = useSyncExternalStore(toastStore.subscribe, toastStore.snapshot);
  const [announcement, setAnnouncement] = useState("");
  const previous = useRef(new Map<number, string>());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    const changed = [...rows].reverse().find(row => previous.current.get(row.id) !== row.message);
    previous.current = new Map(rows.map(row => [row.id, row.message]));
    if (!changed) {
      if (!rows.length) { clearTimeout(timer.current); setAnnouncement(""); }
      return;
    }
    clearTimeout(timer.current);
    setAnnouncement("");
    // A separate DOM update announces repeated messages too, without moving focus.
    timer.current = setTimeout(() => setAnnouncement(changed.message), 50);
  }, [rows]);
  return <>
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement}</div>
    <aside aria-label="Notifications" className="fixed bottom-24 right-4 z-50 grid max-h-[60vh] w-[min(24rem,calc(100vw-2rem))] gap-2 overflow-y-auto">
      {rows.map(row => <div key={row.id} className="desk-panel p-4">
        <p className={`text-sm ${row.tone === "error" ? "text-danger" : "text-ink"}`}>{row.message}</p>
        <div className="mt-2 flex gap-2">
          {row.undo ? <button className="desk-button-secondary" type="button" disabled={row.busy} onClick={() => void undoToast(row.id)}>{row.busy ? "Undoing…" : "Undo"}</button> : null}
          <button className="desk-button-ghost" type="button" disabled={row.busy} onClick={() => dismissToast(row.id)}>Dismiss</button>
        </div>
      </div>)}
    </aside>
  </>;
}
