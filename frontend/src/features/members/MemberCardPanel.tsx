import { useEffect, useState } from "react";

import { StructuredApiError } from "../../lib/api";
import { CardPhotoUpload } from "./memberCard/CardPhotoUpload";
import { useCardPreview, useMyMemberCard, useRenameCard } from "./memberCard/api";

/** The member's own ID card: the printed name they control, their photo, and a
 *  watermarked preview of what the front desk will print. */
export function MemberCardPanel({ makerspaceId }: { makerspaceId: number }) {
  const card = useMyMemberCard(makerspaceId);
  const rename = useRenameCard(makerspaceId);
  const preview = useCardPreview(makerspaceId);
  const [printedName, setPrintedName] = useState("");
  const [dirty, setDirty] = useState(false);

  // Seed from the server, and re-seed only while there is nothing unsaved to lose.
  useEffect(() => {
    if (!card.data || dirty) return;
    setPrintedName(card.data.printed_name);
  }, [card.data, dirty]);

  const notIssued = card.error instanceof StructuredApiError && card.error.status === 404;

  if (card.isLoading) {
    return <section className="desk-panel p-5 text-sm text-muted">Loading your card…</section>;
  }
  if (notIssued) {
    return (
      <section className="desk-panel p-5">
        <h2 className="title-panel">Your member card</h2>
        <p className="mt-1 text-sm text-muted">No card issued yet — ask the front desk.</p>
      </section>
    );
  }
  if (!card.data) {
    return (
      <section className="desk-panel p-5">
        <h2 className="title-panel">Your member card</h2>
        <p className="mt-1 text-sm text-danger" role="alert">
          {card.error instanceof Error ? card.error.message : "Could not load your card."}
        </p>
      </section>
    );
  }

  const row = card.data;

  return (
    <section className="desk-panel p-5">
      <h2 className="title-panel">Your member card</h2>
      <p className="eyebrow mt-2">
        <span className="font-mono">{row.card_number}</span> ·{" "}
        {row.is_active ? "active" : "revoked"} · printed {row.print_count}{" "}
        {row.print_count === 1 ? "time" : "times"}
      </p>

      <label className="mt-4 block text-sm font-medium text-ink" htmlFor="member-card-printed-name">
        Name printed on the card
      </label>
      <input
        id="member-card-printed-name"
        className="desk-input mt-1 w-full"
        value={printedName}
        onChange={(event) => {
          setDirty(true);
          setPrintedName(event.target.value);
        }}
      />
      <div className="desk-actions mt-3 flex flex-wrap gap-2">
        <button
          className="desk-button-secondary"
          type="button"
          disabled={rename.isPending || !printedName.trim()}
          onClick={() =>
            rename.mutate(printedName.trim(), { onSuccess: () => setDirty(false) })
          }
        >
          {rename.isPending ? "Saving…" : "Save name"}
        </button>
        <button
          className="desk-button-ghost"
          type="button"
          disabled={preview.isPending}
          onClick={() => preview.mutate()}
        >
          {preview.isPending ? "Preparing…" : "Preview card (PDF)"}
        </button>
      </div>
      {rename.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {rename.error instanceof Error ? rename.error.message : "Could not save that name."}
        </p>
      ) : null}
      {preview.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {preview.error instanceof Error ? preview.error.message : "Could not open the preview."}
        </p>
      ) : null}

      <CardPhotoUpload
        makerspaceId={makerspaceId}
        photoSet={row.photo_set}
        consentAt={row.photo_consent_at}
      />
    </section>
  );
}
