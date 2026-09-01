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
// Bundle the wasm binary with our own build (Vite emits it under /assets) instead
// of letting zxing-wasm fetch it from the jsdelivr CDN - the strict app CSP only
// allows connect-src 'self', so the CDN fetch would be blocked and detection would
// silently fail on browsers without a native BarcodeDetector (e.g. desktop Windows).
import zxingWasmUrl from "zxing-wasm/reader/zxing_reader.wasm?url";

type QrScannerProps = {
  onScan: (payload: string) => void;
  onClose: () => void;
};

let zxingReaderPromise: Promise<typeof import("zxing-wasm/reader")> | null = null;
const loadZxingReader = () => {
  zxingReaderPromise ??= import("zxing-wasm/reader").then((mod) => {
    mod.setZXingModuleOverrides({ locateFile: () => zxingWasmUrl });
    return mod;
  });
  return zxingReaderPromise;
};

export default function QrScanner({ onScan, onClose }: QrScannerProps) {
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
  const intervalRef = useRef<number | null>(null);
  const detectorRef = useRef<any>(null);
  const nativeFailedRef = useRef(false);
  const onScanRef = useRef(onScan);
  const lastScanRef = useRef({ value: "", at: 0 });
  const isDetectingRef = useRef(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  const stopScanner = () => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  };

  const emitScan = (value: string) => {
    const payload = value.trim();
    const now = Date.now();
    if (!payload) return;
    if (lastScanRef.current.value === payload && now - lastScanRef.current.at < 1500) return;
    lastScanRef.current = { value: payload, at: now };
    onScanRef.current(payload);
  };

  useEffect(() => {
    onScanRef.current = onScan;
  }, [onScan]);
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
    // Initial focus lives HERE, not in the push effect. A dialog that opens while another sits
    // above it renders with `inert` on its layer, and `inert` is only cleared by the re-render
    // that follows becoming topmost -- so focusing from the push effect silently fails, and
    // consumePendingRestore no-ops because nothing was popped. This effect runs post-commit,
    // once `inert` is gone. jsdom implements no `inert` at all, so no unit test can catch this.
    const panel = panelRef.current;
    if (panel && !panel.contains(document.activeElement)) focusFirstDialogElement(panel);
  }, [amTop]);

  useEffect(() => {
    let cancelled = false;

    const detect = async () => {
      const video = videoRef.current;
      if (!video || isDetectingRef.current || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
      isDetectingRef.current = true;
      try {
        if ("BarcodeDetector" in window && !nativeFailedRef.current) {
          try {
            const Detector = (window as any).BarcodeDetector;
            detectorRef.current ??= new Detector({ formats: ["qr_code"] });
            const results = await detectorRef.current.detect(video);
            emitScan(results[0]?.rawValue ?? "");
          } catch {
            // Native BarcodeDetector exists but can't construct/read qr_code on this
            // browser - stop retrying it and fall through to the zxing-wasm reader.
            nativeFailedRef.current = true;
            detectorRef.current = null;
          }
        } else {
          const { readBarcodesFromImageData } = await loadZxingReader();
          const width = video.videoWidth;
          const height = video.videoHeight;
          if (!width || !height) return;
          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const context = canvas.getContext("2d");
          if (!context) return;
          context.drawImage(video, 0, 0, width, height);
          const imageData = context.getImageData(0, 0, width, height);
          const results = await readBarcodesFromImageData(imageData, { formats: ["QRCode"] });
          emitScan(results[0]?.text ?? "");
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "QR scanner could not start.");
        stopScanner();
      } finally {
        isDetectingRef.current = false;
      }
    };

    const getStream = async () => {
      // Secure-context guard: navigator.mediaDevices is undefined over plain HTTP
      // (anything other than localhost / HTTPS), which would otherwise throw an
      // opaque "Cannot read properties of undefined" instead of a clear message.
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error(
          "Camera needs a secure connection (https:// or localhost). Open this site over HTTPS or on the same machine to scan."
        );
      }
      try {
        return await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      } catch (err) {
        // Desktops with only a front webcam can reject the "environment" preference
        // on some setups - retry with any available camera before giving up.
        if (err instanceof DOMException && (err.name === "OverconstrainedError" || err.name === "NotFoundError")) {
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
          // play() can reject (autoplay/AbortError) without meaning the camera failed;
          // the stream is already live, so swallow that rejection.
          try {
            await video.play();
          } catch {
            /* ignore - frames still arrive via the detect() interval */
          }
        }
        setReady(true);
        intervalRef.current = window.setInterval(detect, 400);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Camera access was denied.");
      }
    };

    start();
    return () => {
      cancelled = true;
      stopScanner();
    };
  }, []);

  const close = () => {
    stopScanner();
    onClose();
  };

  return createPortal(
    <div ref={layerRef} inert={!amTop} className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-3 sm:p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <div ref={panelRef} role="dialog" aria-modal={amTop ? "true" : undefined} aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[90vh] w-full max-w-lg flex-col gap-3 overflow-y-auto rounded-lg border border-line bg-panel p-4 shadow-xl outline-none">
        <h2 id={titleId} className="sr-only">QR scanner</h2>
        {error ? (
          <div className="grid gap-3">
            <p className="text-sm text-danger">{error}</p>
            <button className="desk-button w-full" type="button" onClick={close}>
              Close
            </button>
          </div>
        ) : (
          <div className="grid gap-3">
            <div className="relative">
              <video
                ref={videoRef}
                className="aspect-video max-h-[60vh] w-full rounded-md bg-black object-cover"
                autoPlay
                muted
                playsInline
              />
              {!ready ? (
                <p className="absolute inset-0 grid place-items-center text-sm text-white">Starting camera...</p>
              ) : null}
            </div>
            <p className="text-center text-sm text-muted">Point the camera at a QR code</p>
            <button className="desk-button-primary w-full" type="button" onClick={close}>
              Done
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
