import { useState } from "react";
import type { RecoveryReplay } from "./useKioskReplays";
import { useResolveReplay } from "./useKioskReplays";

// Public Station credentials are entered for the current channel, never returned
// from historical recovery data. The Station flow obtains a fresh human lease.
export function KioskReplayResolution({ row }: { row: RecoveryReplay }) {
  const [confirm, setConfirm] = useState(false);
  const [correct, setCorrect] = useState(false);
  const [stationUrl, setStationUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useResolveReplay(row.makerspace_id);
  if (row.resolution_code) return null;

  function openStation() {
    try {
      const url = new URL(stationUrl, window.location.origin);
      if (url.origin !== window.location.origin || !/^\/(?:m\/[^/]+\/)?kiosk\/[^/]+\/?$/.test(url.pathname)) {
        throw new Error("Enter a Station URL on this frontend.");
      }
      url.search = new URLSearchParams({ recovery: row.id }).toString();
      url.hash = "";
      window.location.assign(url.toString());
    } catch { setError("Enter the current handover Station URL on this frontend."); }
  }
  return <div className="mt-3 grid gap-3">
    <div className="flex flex-wrap gap-2">
      <button type="button" className="desk-button-secondary" disabled={mutation.isPending} onClick={() => setConfirm(true)}>Acknowledge — no change occurred</button>
      <button type="button" className="desk-button-secondary" onClick={() => setCorrect(true)}>Correct online</button>
    </div>
    {confirm ? <section className="grid gap-2" aria-label="Confirm no physical change">
      <p className="text-sm">Confirm you verified that no physical change occurred. This records review only and does not alter inventory, the request or the failed evidence.</p>
      <button type="button" className="desk-button-primary" disabled={mutation.isPending} onClick={() => {
        setError(null);
        mutation.mutate({ id: row.id, resolution_code: "acknowledged_no_change" }, {
          onSuccess: () => setConfirm(false), onError: () => setError("Review was refused. Reload current permissions and failure details."),
        });
      }}>{mutation.isPending ? "Recording review…" : "Confirm acknowledgement"}</button>
      <button type="button" className="desk-button-secondary" disabled={mutation.isPending} onClick={() => setConfirm(false)}>Cancel</button>
    </section> : null}
    {correct ? <section className="grid gap-2" aria-label="Correct this handover online">
      {!row.recovery_request_id && !row.recovery_loan_id ? <p className="text-sm">This attempt has no retained subject identity. Staff must inspect the physical handover; a successful replacement cannot be linked safely. Acknowledge only after verifying no change.</p> : <>
        <p className="text-sm">Reconnect, unlock a current handover Station and start an operator shift. Load current work and capture a new command and photo. Only its successful replay can resolve this failure.</p>
        <label className="grid gap-1 text-sm">Current Station URL<input className="desk-input" value={stationUrl} onChange={(event) => setStationUrl(event.target.value)} /></label>
        <button type="button" className="desk-button-primary" disabled={!navigator.onLine || !stationUrl} onClick={openStation}>Open corrective handover</button>
      </>}
    </section> : null}
    {error ? <p role="alert" className="text-sm text-danger">{error}</p> : null}
  </div>;
}
