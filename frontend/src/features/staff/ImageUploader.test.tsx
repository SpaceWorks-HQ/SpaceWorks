import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest, publicV1Request, staffRequest } from "../../lib/api";
import { ImageUploader, uploadPublicImage } from "./ImageUploader";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn(), publicV1Request: vi.fn(), staffRequest: vi.fn() }));
describe("ImageUploader member sessions", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("uses the supplied member session for both presign and attach", async () => {
    vi.mocked(publicV1Request).mockResolvedValue({ public_image_max_bytes: 10000 });
    vi.mocked(memberRequest).mockResolvedValueOnce({ object_key: "profiles/3/image", url: "https://bucket.test", method: "PUT" }).mockResolvedValueOnce({});
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 200 }));
    try {
      await uploadPublicImage("/member/makerspaces/3/profile/image", new File(["image"], "face.png", { type: "image/png" }), { project_id: 2 }, memberRequest);
      expect(memberRequest).toHaveBeenNthCalledWith(1, "/member/makerspaces/3/profile/image", expect.objectContaining({ method: "POST" }));
      expect(memberRequest).toHaveBeenNthCalledWith(2, "/member/makerspaces/3/profile/image", { method: "PUT", body: JSON.stringify({ object_key: "profiles/3/image", project_id: 2 }) });
      expect(staffRequest).not.toHaveBeenCalled();
    } finally { fetchMock.mockRestore(); }
  });
  it("clears a project image using the member session", async () => {
    vi.mocked(memberRequest).mockResolvedValue({}); const changed = vi.fn();
    render(<ImageUploader endpoint="/member/makerspaces/3/profile/image" currentUrl="https://image.test" label="Avatar" clearQuery="?project_id=2" request={memberRequest} onChanged={changed} />);
    fireEvent.click(screen.getByText("Remove"));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/profile/image?project_id=2", { method: "DELETE" });
    expect(staffRequest).not.toHaveBeenCalled();
  });
});
