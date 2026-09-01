import { useEffect, useState } from "react";

import { CameraCapture } from "../../components/ui";
import {
  requestPublicEvidenceUpload,
  uploadPublicEvidenceFile,
} from "./selfCheckoutApi";

export function PublicEvidenceUpload({
  slug,
  evidenceType,
  disabled = false,
  onUploaded,
}: {
  slug: string;
  evidenceType: "issue" | "return";
  disabled?: boolean;
  onUploaded: (evidenceId: number | null) => void;
}) {
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );
  const label = evidenceType === "issue" ? "Issue photo" : "Return photo";

  useEffect(() => {
    setStatus("idle");
    setError("");
    setFileName("");
    setCameraOpen(false);
    onUploaded(null);
  }, [evidenceType, onUploaded]);

  async function handleFile(file: File) {
    setStatus("uploading");
    setError("");
    setFileName(file.name);
    onUploaded(null);
    try {
      const presigned = await requestPublicEvidenceUpload(slug, {
        evidence_type: evidenceType,
        content_type: file.type,
        size_bytes: file.size,
      });
      await uploadPublicEvidenceFile(presigned, file);
      setStatus("done");
      onUploaded(presigned.evidence_id);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed.");
      onUploaded(null);
    }
  }

  return (
    <div className="space-y-1">
      <div className="flex min-w-0 items-end gap-2">
        <label className="block min-w-0 flex-1">
          <span className="eyebrow mb-1 block">
            {label}
          </span>
          <input
            aria-label={label}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={disabled || status === "uploading"}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFile(file);
            }}
            className="block min-h-11 w-full text-sm text-muted file:mr-3 file:min-h-11 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-2 file:text-sm file:font-semibold file:text-on-accent disabled:opacity-60"
          />
        </label>
        {cameraSupported ? (
          <button className="desk-button min-h-11" type="button" aria-label={`Take ${label}`} disabled={disabled || status === "uploading"} onClick={() => setCameraOpen(true)}>
            Camera
          </button>
        ) : null}
      </div>
      <CameraCapture open={cameraOpen} onClose={() => setCameraOpen(false)} onCapture={(file) => { void handleFile(file); }} label={label} />
      {/* ONE persistent live region, not three conditional ones: a role="status" element that is
          inserted at the same moment its text appears is frequently not announced, because the
          region was not in the DOM for the screen reader to observe changing. */}
      <p
        role="status"
        aria-live="polite"
        className={`text-xs ${status === "error" ? "text-danger" : status === "done" ? "text-success-ink" : "text-muted"}`}
      >
        {status === "uploading"
          ? `Uploading ${fileName}...`
          : status === "done"
            ? "Photo uploaded"
            : status === "error"
              ? error
              : ""}
      </p>
    </div>
  );
}
