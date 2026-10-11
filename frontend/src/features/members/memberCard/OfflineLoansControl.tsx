import { useEffect, useState } from "react";
import { readStorage } from "../../../lib/safeStorage";
import { forgetOfflineLoans, OFFLINE_OWNER_KEY, readOfflineLoans, saveOfflineLoans, type OfflineLoan } from "./offlineLoans";

export function OfflineLoansControl({ space, loans }: { space: string; loans: OfflineLoan[] }) {
  const owner = readStorage(OFFLINE_OWNER_KEY);
  const [choice, setChoice] = useState(() => ({ owner, enabled: Boolean(readOfflineLoans()) }));
  const enabled = choice.enabled && choice.owner === owner;
  const [error, setError] = useState("");
  useEffect(() => {
    if (enabled && !saveOfflineLoans(space, loans)) { setChoice({ owner, enabled: false }); setError("This browser could not save offline loans."); }
  }, [space, loans, enabled, owner]);
  return <div className="mt-3 grid gap-2 text-sm">
    <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={enabled} onChange={event => {
      setError("");
      if (event.target.checked) {
        const saved = saveOfflineLoans(space, loans); setChoice({ owner, enabled: saved });
        if (!saved) setError("This browser could not save offline loans.");
      } else { forgetOfflineLoans(); setChoice({ owner, enabled: false }); }
    }} />Keep my loans on this device for offline reading</label>
    {enabled ? <p role="status" className="text-muted">Offline loans show the last saved details. Connect to check current returns and due dates.</p> : null}
    {error ? <p role="alert" className="text-danger">{error}</p> : null}
  </div>;
}
