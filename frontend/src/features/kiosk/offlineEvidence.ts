export const MAX_PHOTO_EDGE = 1600;
export function photoDimensions(width: number, height: number) {
  if (!width || !height) throw new Error("The photo has no pixels. Retake it.");
  const scale = Math.min(1, MAX_PHOTO_EDGE / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

// createImageBitmap applies source orientation; drawing only pixels strips metadata.
// No source URL, filename or EXIF bytes are persisted or logged.
export async function normalizeEvidence(source: Blob, maxBytes: number): Promise<Blob> {
  if (!source.type.startsWith("image/") || !Number.isFinite(maxBytes) || maxBytes < 1) {
    throw new Error("Select a supported photo.");
  }
  if (typeof createImageBitmap !== "function") throw new Error("This browser cannot normalize offline photos. Continue online.");
  const image = await createImageBitmap(source, { imageOrientation: "from-image" });
  const canvas = document.createElement("canvas");
  try {
    const size = photoDimensions(image.width, image.height);
    canvas.width = size.width; canvas.height = size.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Photo capture is unavailable on this browser.");
    context.drawImage(image, 0, 0, size.width, size.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.8));
    if (!blob || blob.type !== "image/jpeg" || blob.size < 1 || blob.size > maxBytes) {
      throw new Error("The normalized photo exceeds the evidence limit. Retake a smaller photo.");
    }
    return blob;
  } finally {
    image.close(); canvas.width = 0; canvas.height = 0;
  }
}
