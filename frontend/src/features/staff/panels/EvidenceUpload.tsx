import { useId, useState } from "react";

import { CameraCapture } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";

type UploadResponse = {
  evidence_id: number;
  upload_url: string;
  fields: Record<string, string>;
  object_key: string;
  method?: string;
  headers?: Record<string, string>;
};

/**
 * Two-step evidence photo upload used by the issue/return flows (hard rule:
 * hardware can't be issued/returned without a photo). Step 1 asks the backend
 * for a presigned POST + an EvidencePhoto row (returns evidence_id). Step 2
 * uploads the file straight to object storage with the presigned fields. The
 * resulting evidence_id is handed back to the parent form via onUploaded.
 */
export function EvidenceUpload({
  makerspaceId,
  evidenceType,
  disabled = false,
  label,
  onUploaded,
}: {
  makerspaceId: number;
  evidenceType: "issue" | "return";
  disabled?: boolean;
  label?: string;
  onUploaded: (evidenceId: number | null) => void;
}) {
  const inputId = useId();
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [error, setError] = useState("");
  const [fileName, setFileName] = useState("");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );

  async function handleFile(file: File) {
    setStatus("uploading");
    setError("");
    setFileName(file.name);
    onUploaded(null); // invalidate any prior upload until this one completes
    try {
      const presigned = await staffRequest<UploadResponse>(
        `/admin/makerspaces/${makerspaceId}/uploads/evidence-url`,
        {
          method: "POST",
          body: JSON.stringify({ evidence_type: evidenceType, content_type: file.type, size_bytes: file.size }),
        },
      );
      if (presigned.method === "PUT") {
        const upload = await fetch(presigned.upload_url, {
          method: "PUT",
          body: file,
          headers: presigned.headers,
        });
        if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
      } else {
        const formData = new FormData();
        Object.entries(presigned.fields).forEach(([key, value]) => formData.append(key, value));
        formData.append("file", file);
        // Direct presigned POST to object storage - no auth header, and we must NOT
        // set Content-Type so the browser adds the multipart boundary itself.
        const upload = await fetch(presigned.upload_url, { method: "POST", body: formData });
        if (!upload.ok) throw new Error(`Storage upload failed (${upload.status})`);
      }
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
      {label ? (
        <label className="block font-medium text-ink" htmlFor={inputId}>
          {label}
        </label>
      ) : null}
      {/* When a visible <label> names the control, aria-label must go: it would override the
          visible text, leaving the accessible name saying something the sighted user never reads. */}
      <div className="flex min-w-0 items-center gap-2">
        <input
          id={inputId}
          aria-label={label ? undefined : `${evidenceType} photo`}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          disabled={disabled || status === "uploading"}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFile(file);
          }}
          className="block min-w-0 flex-1 text-sm text-muted file:mr-3 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-on-accent"
        />
        {cameraSupported ? (
          <button className="desk-button min-h-11" type="button" aria-label={`Take ${label ?? `${evidenceType} photo`}`} disabled={disabled || status === "uploading"} onClick={() => setCameraOpen(true)}>
            Camera
          </button>
        ) : null}
      </div>
      <CameraCapture open={cameraOpen} onClose={() => setCameraOpen(false)} onCapture={(file) => { void handleFile(file); }} label={label ?? `${evidenceType} photo`} />
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
