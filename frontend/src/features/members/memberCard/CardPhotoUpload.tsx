import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { memberCardKey, uploadCardPhoto, useDeleteCardPhoto } from "./api";

const CONSENT_TEXT =
  "I agree to my photo being stored privately for staff to check my card at the door. It is never shown publicly, and it is deleted when this card is revoked.";

/** The member's own card photo.
 *
 *  Consent gates the whole flow, not just the final attach: without the tick nothing is
 *  presigned and nothing reaches the bucket, so an un-consented photo never exists.
 */
export function CardPhotoUpload({
  makerspaceId,
  photoSet,
  consentAt,
}: {
  makerspaceId: number;
  photoSet: boolean;
  consentAt: string | null;
}) {
  const client = useQueryClient();
  const inputId = useId();
  const consentId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const remove = useDeleteCardPhoto(makerspaceId);

  async function upload() {
    if (!file) {
      setStatus("error");
      setError("Choose a photo first.");
      return;
    }
    if (!consent) {
      setStatus("error");
      setError("Tick the consent box before uploading your photo.");
      return;
    }
    setStatus("uploading");
    setError("");
    try {
      await uploadCardPhoto(makerspaceId, file);
      setStatus("done");
      setFile(null);
      await client.invalidateQueries({ queryKey: memberCardKey(makerspaceId) });
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed.");
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-line p-3">
      <h3 className="title-section">Card photo</h3>
      <p className="mt-1 text-sm text-muted">
        {photoSet
          ? consentAt
            ? `Photo on file since ${new Date(consentAt).toLocaleDateString()}.`
            : "Photo on file."
          : "No photo on file yet."}
      </p>

      <label className="mt-3 block text-sm font-medium text-ink" htmlFor={inputId}>
        Choose a photo
      </label>
      <input
        id={inputId}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        disabled={status === "uploading"}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        className="mt-1 block w-full min-w-0 text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-on-accent"
      />

      <label className="mt-3 flex items-start gap-2 text-sm text-ink" htmlFor={consentId}>
        <input
          id={consentId}
          type="checkbox"
          className="mt-1 h-4 w-4"
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <span>{CONSENT_TEXT}</span>
      </label>

      <div className="desk-actions mt-3 flex flex-wrap gap-2">
        <button
          className="desk-button-secondary"
          type="button"
          disabled={status === "uploading"}
          onClick={() => void upload()}
        >
          {status === "uploading" ? "Uploading…" : "Upload photo"}
        </button>
        {photoSet ? (
          <button
            className="desk-button-ghost text-danger"
            type="button"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            {remove.isPending ? "Removing…" : "Remove photo"}
          </button>
        ) : null}
      </div>

      {/* ONE persistent live region, not several conditional ones: a role="status" element
          inserted at the same moment its text appears is frequently not announced. */}
      <p
        role="status"
        aria-live="polite"
        className={`mt-2 text-xs ${status === "error" ? "text-danger" : "text-muted"}`}
      >
        {status === "uploading"
          ? "Uploading your photo…"
          : status === "done"
            ? "Photo uploaded."
            : status === "error"
              ? error
              : ""}
      </p>
      {remove.error ? (
        <p className="mt-1 text-xs text-danger" role="alert">
          {remove.error instanceof Error ? remove.error.message : "Could not remove the photo."}
        </p>
      ) : null}
    </div>
  );
}
