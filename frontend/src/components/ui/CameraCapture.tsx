import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import {
  consumePendingRestore,
  focusFirstDialogElement,
  getSnapshot,
  popDialog,
  pushDialog,
  subscribe,
  trapDialogFocus,
} from "./dialogFocus";

type CameraCaptureProps = {
  open: boolean;
  onClose: () => void;
  onCapture: (file: File) => void;
  label?: string;
};

const CAPTURE_BUDGET_BYTES = 4 * 1024 * 1024;
const LONG_EDGE_STEPS = [2048, 1600, 1280] as const;
const QUALITY_STEPS = [0.9, 0.75, 0.6] as const;
const SECURE_CONTEXT_ERROR =
  "Camera needs a secure connection (https:// or localhost). Open this site over HTTPS or on the same machine to scan.";

function cameraErrorMessage(error: unknown) {
  if (error instanceof Error && error.message === SECURE_CONTEXT_ERROR) return error.message;
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "Camera permission was denied. Allow camera access in your browser and try again.";
    }
    if (error.name === "NotFoundError") return "No camera was found on this device.";
  }
  return "The camera could not start. Close this window and try again.";
}

function canvasToBlob(canvas: HTMLCanvasElement, quality: number) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("The captured photo could not be encoded. Please retake it."));
    }, "image/jpeg", quality);
  });
}

function blobToDataUrl(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("The captured photo preview could not be created."));
    };
    reader.onerror = () => reject(new Error("The captured photo preview could not be created."));
    reader.readAsDataURL(blob);
  });
}

export function CameraCapture({ open, onClose, onCapture, label }: CameraCaptureProps) {
  if (!open) return null;
  return <OpenCameraCapture onClose={onClose} onCapture={onCapture} label={label} />;
}

function OpenCameraCapture({ onClose, onCapture, label }: Omit<CameraCaptureProps, "open">) {
  const titleId = useId();
  const layerRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const tokenRef = useRef<symbol | null>(null);
  const top = useSyncExternalStore(subscribe, getSnapshot);
  const amTop = top === tokenRef.current;
  const amTopRef = useRef(amTop);
  amTopRef.current = amTop;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [captured, setCaptured] = useState<{ file: File; preview: string } | null>(null);

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }

  function close() {
    stopCamera();
    onCloseRef.current();
  }

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const token = pushDialog({
      previousFocus,
      getPanel: () => panelRef.current,
      getLayer: () => layerRef.current,
    });
    tokenRef.current = token;
    const panel = panelRef.current;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (!amTopRef.current) return;
      if (event.key === "Escape") close();
      if (panel) trapDialogFocus(event, panel);
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      popDialog(token);
      if (tokenRef.current === token) tokenRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!amTop) return;
    consumePendingRestore(panelRef.current);
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) focusFirstDialogElement(panel);
  }, [amTop]);

  useEffect(() => {
    let cancelled = false;

    const getStream = async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(SECURE_CONTEXT_ERROR);
      }
      try {
        return await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      } catch (err) {
        if (err instanceof DOMException && (err.name === "OverconstrainedError" || err.name === "NotFoundError")) {
          // The first attempt can reject AFTER the dialog closed. Firing the fallback anyway would
          // raise a permission prompt, or briefly light the camera, on a dialog the user has shut.
          if (cancelled) throw err;
          return await navigator.mediaDevices.getUserMedia({ video: true });
        }
        throw err;
      }
    };

    const start = async () => {
      try {
        const stream = await getStream();
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          try {
            await video.play();
          } catch {
            /* The live stream can still deliver frames after an autoplay rejection. */
          }
          if (cancelled) return;
          setReady(video.videoWidth > 0 && video.videoHeight > 0);
        }
      } catch (err) {
        stopCamera();
        if (!cancelled) setError(cameraErrorMessage(err));
      }
    };

    setCaptured(null);
    setError("");
    setCapturing(false);
    start();
    return () => {
      cancelled = true;
      stopCamera();
    };
  }, []);

  const updateReady = () => {
    const video = videoRef.current;
    setReady(Boolean(video && video.videoWidth > 0 && video.videoHeight > 0));
  };

  const takePhoto = async () => {
    const video = videoRef.current;
    if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) return;
    setCapturing(true);
    setError("");
    try {
      const canvas = document.createElement("canvas");
      const context = canvas.getContext("2d");
      if (!context) throw new Error("The captured photo could not be processed. Please retake it.");

      let selectedBlob: Blob | null = null;
      captureLoop: for (const longEdge of LONG_EDGE_STEPS) {
        const scale = Math.min(1, longEdge / Math.max(video.videoWidth, video.videoHeight));
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        for (const quality of QUALITY_STEPS) {
          selectedBlob = await canvasToBlob(canvas, quality);
          if (selectedBlob.size <= CAPTURE_BUDGET_BYTES) break captureLoop;
        }
      }

      if (!selectedBlob) throw new Error("The captured photo could not be encoded. Please retake it.");
      const file = new File([selectedBlob], `capture-${Date.now()}.jpg`, { type: "image/jpeg" });
      const preview = await blobToDataUrl(selectedBlob);
      setCaptured({ file, preview });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The photo could not be captured. Please try again.");
    } finally {
      setCapturing(false);
    }
  };

  const title = label ?? "Take photo";
  return createPortal(
    <div
      ref={layerRef}
      inert={!amTop}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-3 sm:p-4"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}
    >
      <div ref={panelRef} role="dialog" aria-modal={amTop ? "true" : undefined} aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[90vh] w-full max-w-lg flex-col gap-3 overflow-y-auto rounded-lg border border-line bg-panel p-4 shadow-xl outline-none">
        <h2 id={titleId} className="text-lg font-semibold text-ink">{title}</h2>
        <div aria-live="assertive" aria-atomic="true">
          {error ? <p className="text-sm text-danger">{error}</p> : null}
        </div>
        <div className={captured ? "hidden" : "relative"}>
          <video ref={videoRef} className="max-h-[60vh] w-full rounded-md bg-black object-contain" autoPlay playsInline muted onLoadedMetadata={updateReady} onCanPlay={updateReady} />
          {!ready && !error ? <p className="absolute inset-0 grid place-items-center text-sm text-white">Starting camera...</p> : null}
        </div>
        {captured ? (
          <>
            <img src={captured.preview} alt="Captured photo preview" className="max-h-[60vh] w-full rounded-md bg-black object-contain" />
            <div className="grid gap-2 sm:grid-cols-2">
              <button className="desk-button min-h-11" type="button" onClick={() => { setCaptured(null); setError(""); }}>
                Retake
              </button>
              <button className="desk-button-primary min-h-11" type="button" onClick={() => { onCapture(captured.file); close(); }}>
                Use photo
              </button>
            </div>
          </>
        ) : (
          <button className="desk-button-primary min-h-11 w-full" type="button" disabled={!ready || capturing} onClick={takePhoto}>
            {capturing ? "Capturing..." : "Take photo"}
          </button>
        )}
        <button className="desk-button min-h-11 w-full" type="button" onClick={close}>Cancel</button>
      </div>
    </div>,
    document.body,
  );
}
