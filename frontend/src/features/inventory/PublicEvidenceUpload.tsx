import { useEffect, useState } from "react";

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
  const label = evidenceType === "issue" ? "Issue photo" : "Return photo";

  useEffect(() => {
    setStatus("idle");
    setError("");
    setFileName("");
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
      <label className="block">
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
      {status === "uploading" ? <p className="text-xs text-muted">Uploading {fileName}...</p> : null}
      {status === "done" ? <p className="text-xs text-success-ink">Photo uploaded</p> : null}
      {status === "error" ? <p className="text-xs text-danger">{error}</p> : null}
    </div>
  );
}
