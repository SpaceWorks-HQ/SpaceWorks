import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizeEvidence, photoDimensions } from "./offlineEvidence";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("offline photo normalization", () => {
  it("bounds portrait/landscape dimensions and never upscales", () => {
    expect(photoDimensions(4000, 2000)).toEqual({ width: 1600, height: 800 });
    expect(photoDimensions(2000, 4000)).toEqual({ width: 800, height: 1600 });
    expect(photoDimensions(640, 480)).toEqual({ width: 640, height: 480 });
    expect(() => photoDimensions(0, 200)).toThrow();
  });
  it("uses oriented decoded pixels, encodes fresh JPEG bytes and releases pixels", async () => {
    const close = vi.fn(); const bitmap = { width: 4000, height: 2000, close };
    const decode = vi.fn().mockResolvedValue(bitmap); vi.stubGlobal("createImageBitmap", decode);
    const draw = vi.fn(); vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: draw } as unknown as CanvasRenderingContext2D);
    const normalized = new Blob(["fresh-pixels"], { type: "image/jpeg" });
    const encode = vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(normalized));
    const source = new Blob(["EXIF GPS PRIVATE SOURCE"], { type: "image/jpeg" });
    expect(await normalizeEvidence(source, 1000)).toBe(normalized);
    expect(decode).toHaveBeenCalledWith(source, { imageOrientation: "from-image" });
    expect(draw).toHaveBeenCalledWith(bitmap, 0, 0, 1600, 800);
    expect(encode).toHaveBeenCalledWith(expect.any(Function), "image/jpeg", 0.8);
    expect(close).toHaveBeenCalled();
  });
  it("blocks oversize/empty output and releases the decoded bitmap on failure", async () => {
    const close = vi.fn(); vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue({ width: 10, height: 10, close }));
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => callback(new Blob(["too large"], { type: "image/jpeg" })));
    await expect(normalizeEvidence(new Blob(["source"], { type: "image/jpeg" }), 1)).rejects.toThrow("exceeds");
    expect(close).toHaveBeenCalled();
    vi.mocked(HTMLCanvasElement.prototype.toBlob).mockImplementation((callback) => callback(null));
    await expect(normalizeEvidence(new Blob(["source"], { type: "image/jpeg" }), 100)).rejects.toThrow("exceeds");
  });
});
