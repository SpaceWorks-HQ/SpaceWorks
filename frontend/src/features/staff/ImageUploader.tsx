import { useEffect, useId, useRef, useState } from "react";

import { CameraCapture } from "../../components/ui";
import { publicV1Request, staffRequest } from "../../lib/api";

type PresignResponse = {
  object_key: string;
  url: string;
  fields?: Record<string, string>;
  method?: string;
  headers?: Record<string, string>;
};

type PublicConfigResponse = {
  public_image_max_bytes: number;
};

let publicImageMaxBytesPromise: Promise<number> | null = null;

async function getPublicImageMaxBytes() {
  if (!publicImageMaxBytesPromise) {
    publicImageMaxBytesPromise = publicV1Request<PublicConfigResponse>("/config").then(
      (config) => {
        const cap = Number(config.public_image_max_bytes);
        if (!Number.isFinite(cap) || cap <= 0) {
          throw new Error("Image upload limit is unavailable.");
        }
        return cap;
      },
    );
  }
  return publicImageMaxBytesPromise;
}

async function rejectOversizePublicImage(file: File) {
  const cap = await getPublicImageMaxBytes();
  if (file.size > cap) {
    throw new Error(`Image too large (max ${Math.round(cap / 1048576)} MB).`);
  }
}

export async function uploadPublicImage(
  endpoint: string,
  file: File,
  // Extra fields carried on BOTH the presign and the attach — the member profile
  // endpoints use one triple for the avatar and for each project image, discriminated
  // by `project_id`, and the attach needs it as much as the presign does.
  extraBody: Record<string, unknown> = {},
) {
  await rejectOversizePublicImage(file);
  const presigned = await staffRequest<PresignResponse>(endpoint, {
    method: "POST",
    body: JSON.stringify({
      content_type: file.type || "application/octet-stream",
      filename: file.name,
      ...extraBody,
    }),
  });

  if (presigned.method === "PUT") {
    const res = await fetch(presigned.url, {
      method: "PUT",
      body: file,
      headers: presigned.headers,
    });
    if (!res.ok) throw new Error(`Storage upload failed (${res.status})`);
  } else {
    const formData = new FormData();
    Object.entries(presigned.fields ?? {}).forEach(([k, v]) => formData.append(k, v));
    formData.append("file", file);
    const res = await fetch(presigned.url, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Storage upload failed (${res.status})`);
  }

  await staffRequest(endpoint, {
    method: "PUT",
    body: JSON.stringify({ object_key: presigned.object_key, ...extraBody }),
  });
}
type ImageUploaderProps = {
  /** Admin endpoint base, e.g. `/admin/inventory/12/image` or `/admin/makerspace/3/logo`. */
  endpoint: string;
  /** Current public image URL (preview), or null/empty when none. */
  currentUrl?: string | null;
  label: string;
  /** Called after a successful attach or clear so the parent can refetch. */
  onChanged: () => void;
  disabled?: boolean;
  /** object-contain (logos) vs object-cover (photos). */
  fit?: "cover" | "contain";
  /** square preview (logos/thumbnails) vs wide banner preview (cover images). */
  shape?: "square" | "wide";
  /** Extra fields sent with presign, attach and clear (e.g. `{ project_id }`). */
  extraBody?: Record<string, unknown>;
  /** Query string appended to the clear request, which carries no body. */
  clearQuery?: string;
};

/**
 * Reusable public-image uploader for staff (item photos, makerspace logo/cover).
 * Drives the Phase-2 flow: POST -> presign, upload via the returned method
 * (POST multipart or PUT), then PUT { object_key } to finalize+attach. The
 * storage upload itself is an unauthenticated direct-to-bucket request.
 */
export function ImageUploader({
  endpoint,
  currentUrl,
  label,
  onChanged,
  disabled = false,
  fit = "cover",
  shape = "square",
  extraBody,
  clearQuery = "",
}: ImageUploaderProps) {
  const inputId = useId();
  const objectUrlRef = useRef<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  // Cover images are wide banners - give them a rectangular preview that matches
  // how they render publicly, instead of cropping into an 80x80 square.
  const previewBox = shape === "wide" ? "h-24 w-full sm:h-20 sm:w-44" : "h-20 w-20";
  const [status, setStatus] = useState<"idle" | "uploading" | "error">("idle");
  const [error, setError] = useState("");
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraSupported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia,
  );
  // Drive the preview from local state so an upload/remove reflects immediately,
  // even though the parent's `currentUrl` (a snapshot) only refreshes on its next
  // refetch. Re-sync whenever the parent does send a new URL.
  const [preview, setPreview] = useState<string | null>(currentUrl ?? null);
  useEffect(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setPreview(currentUrl ?? null);
  }, [currentUrl]);

  useEffect(() => () => {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  function setLocalPreview(file: File) {
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = URL.createObjectURL(file);
    setPreview(objectUrlRef.current);
  }

  async function handleFile(file: File) {
    setStatus("uploading");
    setError("");
    try {
      await uploadPublicImage(endpoint, file, extraBody);
      setStatus("idle");
      setLocalPreview(file);
      onChanged();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function clearImage() {
    setStatus("uploading");
    setError("");
    try {
      await staffRequest(`${endpoint}${clearQuery}`, { method: "DELETE" });
      setStatus("idle");
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
      setPreview(null);
      onChanged();
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : "Could not remove image.");
    }
  }

  return (
    <div className="min-w-0 space-y-2">
      <label htmlFor={inputId} className="block font-mono text-xs uppercase tracking-tight text-muted">{label}</label>
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
        <div className={`${previewBox} shrink-0 overflow-hidden rounded-lg border border-line bg-surface`}>
          {preview ? (
            <img
              src={preview}
              alt={label}
              className={`h-full w-full ${fit === "contain" ? "object-contain" : "object-cover"}`}
            />
          ) : (
            <div className="blueprint-bg grid h-full w-full place-items-center font-mono text-[10px] uppercase text-muted">
              none
            </div>
          )}
        </div>
        <div className="min-w-0 max-w-full space-y-1">
          <div className="flex min-w-0 items-center gap-2">
            <input
              id={inputId}
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={disabled || status === "uploading"}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) handleFile(file);
              }}
              className="block w-full max-w-full min-w-0 flex-1 text-sm text-muted file:mr-3 file:rounded-lg file:border file:border-line file:bg-accent file:px-3 file:py-1.5 file:font-mono file:text-xs file:font-semibold file:text-on-accent"
            />
            {cameraSupported ? (
              <button className="desk-button min-h-11" type="button" aria-label={`Take ${label} photo`} disabled={disabled || status === "uploading"} onClick={() => setCameraOpen(true)}>
                Camera
              </button>
            ) : null}
          </div>
          <CameraCapture open={cameraOpen} onClose={() => setCameraOpen(false)} onCapture={(file) => { void handleFile(file); }} label={label} />
          {preview ? (
            <button
              type="button"
              className="desk-button-ghost px-0 font-mono text-xs uppercase text-danger"
              disabled={disabled || status === "uploading"}
              onClick={clearImage}
            >
              Remove
            </button>
          ) : null}
          {/* ONE persistent live region, not two conditional ones: a role="status" element that is
              inserted at the same moment its text appears is frequently not announced, because the
              region was not in the DOM for the screen reader to observe changing. */}
          <p
            role="status"
            aria-live="polite"
            className={status === "error" ? "text-xs text-danger" : "font-mono text-xs text-muted"}
          >
            {status === "uploading" ? "Working..." : status === "error" ? error : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
