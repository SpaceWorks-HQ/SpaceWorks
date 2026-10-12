import { useState } from "react";

import { Badge } from "../../../../components/ui";
import QrScanner from "../../../../components/ui/QrScanner";
import { useResolveCard } from "./api";

const OUTCOME_TEXT = {
  ok: "Card valid — admit this member.",
  revoked: "Card revoked — do not accept it.",
  inactive: "Membership not active — do not accept this card.",
} as const;

/** Front-desk lookup: type, paste or scan a card payload and see whether it is good.
 *
 *  A refused card shows the outcome and NOTHING else. The backend withholds the holder's
 *  name for `revoked`/`inactive` precisely so a revoked card cannot be used to read a
 *  member's identity off the console, and echoing any field it did return would undo that.
 */
export function ScanCardBox({ makerspaceId }: { makerspaceId: number }) {
  const [payload, setPayload] = useState("");
  const [scannerOpen, setScannerOpen] = useState(false);
  const resolve = useResolveCard(makerspaceId);
  const result = resolve.data;

  const lookup = (value: string) => {
    if (value.trim()) resolve.mutate(value);
  };

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h3 className="title-section">Scan card</h3>
      <p className="mt-1 text-sm text-muted">
        Scan or paste a card payload to check whether it is still valid.
      </p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="member-card-payload">
          Card payload
        </label>
        <input
          id="member-card-payload"
          className="desk-input w-full font-mono sm:flex-1"
          placeholder="Paste card payload (or scan)"
          value={payload}
          onChange={(event) => setPayload(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") lookup(payload);
          }}
        />
        <button
          className="desk-button-primary w-full sm:w-auto"
          type="button"
          disabled={!payload.trim() || resolve.isPending}
          onClick={() => lookup(payload)}
        >
          {resolve.isPending ? "Checking…" : "Check card"}
        </button>
        <button
          className="desk-button-ghost w-full sm:w-auto"
          type="button"
          onClick={() => setScannerOpen(true)}
        >
          Scan
        </button>
      </div>

      {/* One persistent live region: an element inserted at the same moment its text
          appears is often not announced, because there was nothing for the screen
          reader to observe changing. */}
      <div role="status" aria-live="polite" className="mt-3 min-h-6">
        {resolve.isPending ? <p className="text-sm text-muted">Checking card…</p> : null}
        {result && !resolve.isPending ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={result.outcome === "ok" ? "success" : "danger"}>{result.outcome}</Badge>
            <span className="text-sm text-ink">{OUTCOME_TEXT[result.outcome]}</span>
          </div>
        ) : null}
      </div>
      {result?.outcome === "ok" && !resolve.isPending ? (
        <dl className="mt-3 grid gap-1 text-sm sm:grid-cols-[auto_1fr] sm:gap-x-3">
          <dt className="text-muted">Card</dt>
          <dd className="font-mono text-xs text-ink">{result.card_number}</dd>
          <dt className="text-muted">Name</dt>
          <dd className="text-ink">{result.printed_name}</dd>
          <dt className="text-muted">Membership</dt>
          <dd className="text-ink">{result.membership_status}</dd>
        </dl>
      ) : null}
      {result?.outcome === "ok" && result.photo_url ? (
        <img
          className="mt-3 h-24 w-24 rounded-lg border border-line object-cover"
          src={result.photo_url}
          alt={`Photo on file for ${result.printed_name ?? "this card"}`}
        />
      ) : null}
      {resolve.error ? (
        <p className="mt-3 text-sm text-danger" role="alert">
          {resolve.error instanceof Error ? resolve.error.message : "Could not check that card."}
        </p>
      ) : null}

      {scannerOpen ? (
        <QrScanner
          onClose={() => setScannerOpen(false)}
          // The payload is a physical-possession token, so a camera scan resolves it
          // WITHOUT echoing it into the visible input.
          onScan={(value) => {
            setScannerOpen(false);
            lookup(value);
          }}
        />
      ) : null}
    </div>
  );
}
