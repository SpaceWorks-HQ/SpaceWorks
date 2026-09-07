import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";
import { MemberCardPanel } from "./MemberCardPanel";

const { memberRequest, memberRequestBlob } = vi.hoisted(() => ({
  memberRequest: vi.fn(),
  memberRequestBlob: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, memberRequest, memberRequestBlob };
});

const CARD_PATH = "/member/makerspaces/5/member-card";
const PHOTO_PATH = `${CARD_PATH}/photo`;

const card = {
  id: 3,
  card_number: 103,
  printed_name: "Grace Hopper",
  membership_id: 12,
  is_active: true,
  photo_set: false,
  photo_consent_at: null,
  qr_active: true,
  print_count: 1,
  last_printed_at: "2026-08-20T10:00:00Z",
  issued_at: "2026-07-01T10:00:00Z",
  revoked_at: null,
  revoked_reason: "",
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-08-20T10:00:00Z",
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemberCardPanel makerspaceId={5} />
    </QueryClientProvider>,
  );
}

function chooseFile() {
  const input = screen.getByLabelText("Choose a photo") as HTMLInputElement;
  const file = new File(["bytes"], "me.png", { type: "image/png" });
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  memberRequest.mockReset();
  memberRequestBlob.mockReset();
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200 }) as unknown as Response));
});

describe("MemberCardPanel", () => {
  it("tells a member with no card to ask the front desk", async () => {
    memberRequest.mockRejectedValue(new StructuredApiError(404, { detail: "Not found." }));

    const { container } = renderPanel();

    expect(await screen.findByText("No card issued yet — ask the front desk.")).toBeVisible();
    await expectNoA11yViolations(container);
  });

  it("refuses to upload a photo until consent is given, then completes both steps", async () => {
    memberRequest.mockImplementation((path: string) =>
      path === CARD_PATH ? Promise.resolve(card) : Promise.resolve({
        object_key: "staging/cards/3.png",
        content_type: "image/png",
        url: "https://storage.example/bucket",
        fields: { key: "staging/cards/3.png" },
      }),
    );

    const { container } = renderPanel();

    expect(await screen.findByText(/103/)).toBeVisible();
    chooseFile();
    fireEvent.click(screen.getByRole("button", { name: "Upload photo" }));

    expect(
      await screen.findByText("Tick the consent box before uploading your photo."),
    ).toBeVisible();
    expect(memberRequest).not.toHaveBeenCalledWith(PHOTO_PATH, expect.anything());
    expect(fetch).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("checkbox", { name: /I agree to my photo being stored privately/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Upload photo" }));

    // Step 1 presigns, the bucket write happens with no auth header, then step 2 attaches
    // the object WITH the consent flag - that PUT is the record of the member agreeing.
    await waitFor(() =>
      expect(memberRequest).toHaveBeenCalledWith(
        PHOTO_PATH,
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            object_key: "staging/cards/3.png",
            content_type: "image/png",
            consent: true,
          }),
        }),
      ),
    );
    expect(fetch).toHaveBeenCalledWith(
      "https://storage.example/bucket",
      expect.objectContaining({ method: "POST" }),
    );
    await expectNoA11yViolations(container);
  });

  it("saves an edited printed name", async () => {
    memberRequest.mockResolvedValue(card);

    renderPanel();

    const input = await screen.findByLabelText("Name printed on the card");
    fireEvent.change(input, { target: { value: "G. Hopper" } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));

    await waitFor(() =>
      expect(memberRequest).toHaveBeenCalledWith(
        CARD_PATH,
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ printed_name: "G. Hopper" }),
        }),
      ),
    );
  });
});
