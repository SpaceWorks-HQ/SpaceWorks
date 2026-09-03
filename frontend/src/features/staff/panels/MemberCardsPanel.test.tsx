import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../../test/axe";
import { MemberCardsPanel } from "./MemberCardsPanel";

const { staffRequest, staffRequestBlob } = vi.hoisted(() => ({
  staffRequest: vi.fn(),
  staffRequestBlob: vi.fn(),
}));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest, staffRequestBlob };
});

const card = {
  id: 4,
  card_number: 104,
  printed_name: "Ada Lovelace",
  membership_id: 11,
  is_active: true,
  photo_set: true,
  photo_consent_at: "2026-08-01T10:00:00Z",
  qr_active: true,
  print_count: 2,
  last_printed_at: "2026-08-20T10:00:00Z",
  issued_at: "2026-07-01T10:00:00Z",
  revoked_at: null,
  revoked_reason: "",
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-08-20T10:00:00Z",
};

const template = {
  version: 1,
  page: "a4" as const,
  orientation: "portrait" as const,
  card_width_mm: 85.6,
  card_height_mm: 54,
  margin_mm: 10,
  gap_mm: 4,
  front_fields: ["printed_name", "card_number"],
  back_text: "Return to the front desk if found.",
  include_photo: true,
  include_qr: true,
  name_font_size_pt: 14,
  font_size_pt: 9,
  crop_marks: true,
};

// Two memberships: one already carries `card` (id 11) and must NOT appear in the issue
// roster, one has no card (id 12) and must.
const memberships = [
  { id: 11, user: { username: "ada", display_name: "Ada Lovelace" }, status: "active" },
  { id: 12, user: { username: "grace" }, status: "active" },
];

function route(path: string) {
  if (path.includes("member-cards?status=active")) {
    return Promise.resolve({ count: 1, next: null, previous: null, results: [card] });
  }
  if (path.includes("member-cards?status=revoked")) {
    return Promise.resolve({ count: 0, next: null, previous: null, results: [] });
  }
  if (path.endsWith("/memberships")) return Promise.resolve(memberships);
  if (path.endsWith("/member-card-template")) return Promise.resolve(template);
  return Promise.resolve(card);
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemberCardsPanel makerspaceId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequestBlob.mockReset();
  staffRequest.mockImplementation(route);
  staffRequestBlob.mockResolvedValue(new Blob(["pdf"]));
});

describe("MemberCardsPanel", () => {
  it("lists the active cards and the members still without one", async () => {
    const { container } = renderPanel();

    expect(await screen.findByText("104")).toBeVisible();
    expect(screen.getByText("Ada Lovelace")).toBeVisible();
    expect(screen.getAllByText("active").length).toBeGreaterThan(0);
    // grace holds no card; ada already does, so only grace is offered an issue button.
    expect(await screen.findByText("grace")).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Issue card" })).toHaveLength(1);

    await expectNoA11yViolations(container);
  });

  it("issues a card for the selected membership", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Issue card" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/makerspaces/7/member-cards/12/issue",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("asks for confirmation before revoking a card", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    // The dialog is up and nothing has been sent yet.
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalledWith(
      "/admin/member-cards/4/revoke",
      expect.anything(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Revoke card" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/member-cards/4/revoke",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("prints a single card through the blob endpoint", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Print" }));

    await waitFor(() =>
      expect(staffRequestBlob).toHaveBeenCalledWith(
        "/admin/member-cards/4/print.pdf",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
