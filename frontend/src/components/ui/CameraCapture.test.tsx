import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicEvidenceUpload } from "../../features/inventory/PublicEvidenceUpload";
import { ImageUploader } from "../../features/staff/ImageUploader";
import { EvidenceUpload } from "../../features/staff/panels/EvidenceUpload";
import { CameraCapture } from "./CameraCapture";

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");

function installGetUserMedia(getUserMedia: ReturnType<typeof vi.fn> | undefined) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: getUserMedia ? { getUserMedia } : undefined,
  });
}

function makeStream(stop = vi.fn()) {
  return {
    stop,
    stream: { getTracks: () => [{ stop }] } as unknown as MediaStream,
  };
}

function CaptureHarness({ onCapture }: { onCapture: (file: File) => void }) {
  const [open, setOpen] = useState(true);
  return <CameraCapture open={open} onClose={() => setOpen(false)} onCapture={onCapture} />;
}

async function readyCamera() {
  const dialog = await screen.findByRole("dialog");
  // Testing Library has no semantic video query, so use the dialog-owned element.
  const cameraVideo = dialog.querySelector("video");
  if (!cameraVideo) throw new Error("Camera video was not rendered");
  fireEvent.loadedMetadata(cameraVideo);
  const shutter = screen.getByRole("button", { name: "Take photo" });
  await waitFor(() => expect(shutter).toBeEnabled());
  return shutter;
}

beforeEach(() => {
  const { stream } = makeStream();
  installGetUserMedia(vi.fn().mockResolvedValue(stream));
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1600);
  vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1200);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
});

afterEach(() => {
  vi.restoreAllMocks();
  if (originalMediaDevices) Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  else Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("CameraCapture", () => {
  it("renders nothing while closed and hides all uploader camera buttons without mediaDevices", () => {
    installGetUserMedia(undefined);
    const onUploaded = vi.fn();

    const closed = render(<CameraCapture open={false} onClose={vi.fn()} onCapture={vi.fn()} />);
    expect(closed.container).toBeEmptyDOMElement();
    closed.unmount();

    render(
      <>
        <PublicEvidenceUpload slug="space" evidenceType="issue" onUploaded={onUploaded} />
        <EvidenceUpload makerspaceId={1} evidenceType="return" onUploaded={onUploaded} />
        <ImageUploader endpoint="/admin/inventory/1/image" label="Item image" onChanged={vi.fn()} />
      </>,
    );

    expect(screen.queryByRole("button", { name: "Camera" })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/photo|image/i)).toHaveLength(3);
  });

  it.each(["OverconstrainedError", "NotFoundError"])(
    "falls back to any camera for %s",
    async (errorName) => {
      const { stream } = makeStream();
      const getUserMedia = vi.fn()
        .mockRejectedValueOnce(new DOMException("preferred camera unavailable", errorName))
        .mockResolvedValueOnce(stream);
      installGetUserMedia(getUserMedia);

      render(<CameraCapture open onClose={vi.fn()} onCapture={vi.fn()} />);

      await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
      expect(getUserMedia).toHaveBeenNthCalledWith(1, { video: { facingMode: "environment" } });
      expect(getUserMedia).toHaveBeenNthCalledWith(2, { video: true });
    },
  );

  it("does not retry a permission denial", async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    installGetUserMedia(getUserMedia);

    render(<CameraCapture open onClose={vi.fn()} onCapture={vi.fn()} />);

    expect(await screen.findByText(/camera permission was denied/i)).toBeInTheDocument();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("delivers a JPEG File only after Use photo", async () => {
    const onCapture = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      callback(new Blob([new Uint8Array(1024)], { type: "image/jpeg" }));
    });
    render(<CaptureHarness onCapture={onCapture} />);

    fireEvent.click(await readyCamera());
    const usePhoto = await screen.findByRole("button", { name: "Use photo" });
    expect(onCapture).not.toHaveBeenCalled();

    fireEvent.click(usePhoto);

    expect(onCapture).toHaveBeenCalledTimes(1);
    const captured = onCapture.mock.calls[0][0] as File;
    expect(captured).toBeInstanceOf(File);
    expect(captured.type).toBe("image/jpeg");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("surfaces a null canvas blob as an error", async () => {
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(null));
    render(<CameraCapture open onClose={vi.fn()} onCapture={vi.fn()} />);

    fireEvent.click(await readyCamera());

    expect(await screen.findByText(/could not be encoded/i)).toBeInTheDocument();
  });

  it("stops the active track on close", async () => {
    const { stop, stream } = makeStream();
    installGetUserMedia(vi.fn().mockResolvedValue(stream));
    render(<CaptureHarness onCapture={vi.fn()} />);

    const video = screen.getByRole("dialog").querySelector("video") as HTMLVideoElement;
    await waitFor(() => expect(video.srcObject).toBe(stream));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(stop).toHaveBeenCalled();
  });

  it("stops tracks when acquisition resolves after close", async () => {
    const { stop, stream } = makeStream();
    let resolveStream: ((stream: MediaStream) => void) | undefined;
    const pendingStream = new Promise<MediaStream>((resolve) => { resolveStream = resolve; });
    const getUserMedia = vi.fn().mockReturnValue(pendingStream);
    installGetUserMedia(getUserMedia);
    render(<CaptureHarness onCapture={vi.fn()} />);
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(async () => resolveStream?.(stream));

    await waitFor(() => expect(stop).toHaveBeenCalled());
  });
});
