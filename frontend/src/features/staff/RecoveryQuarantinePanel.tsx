import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";

export type RecoveryState = {
  mode: "normal" | "quiesced" | "quarantined";
  quarantine_reason: string;
  quarantined_at: string | null;
  residual_risk: string;
};

export function RecoveryQuarantinePanel({ state, onAcknowledged }: { state: RecoveryState; onAcknowledged: (state: RecoveryState) => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const acknowledge = useMutation({
    mutationFn: () => staffRequest<RecoveryState>("/recovery", {
      method: "POST",
      body: JSON.stringify({ acknowledgement: state.residual_risk }),
    }),
    onSuccess: onAcknowledged,
  });
  return (
    <main className="desk-shell grid place-items-center px-5">
      <section className="desk-panel w-full max-w-2xl p-6">
        <SpaceWorksBadge className="mb-5" />
        <p className="eyebrow text-danger">Recovery quarantine</p>
        <h1 className="mt-2 text-2xl font-bold text-ink">Authority is suspended</h1>
        <p className="mt-3 text-sm text-muted">{state.quarantine_reason}</p>
        <div className="mt-5 rounded-md border border-danger/40 bg-danger/5 p-4 text-sm text-ink">
          <p className="font-semibold">Residual risk</p>
          <p className="mt-2">{state.residual_risk}</p>
        </div>
        <label className="mt-5 flex items-start gap-3 text-sm text-ink">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          I reviewed the restore report where one exists and accept this exact residual risk.
        </label>
        <button className="desk-button-danger mt-5" type="button" disabled={!confirmed || acknowledge.isPending} onClick={() => acknowledge.mutate()}>
          {acknowledge.isPending ? "Acknowledging…" : "Lift quarantine"}
        </button>
        {acknowledge.error ? <p className="mt-3 text-sm text-danger" role="alert">{acknowledge.error.message}</p> : null}
      </section>
    </main>
  );
}

