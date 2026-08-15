import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemberClaimCodes, type ClaimableMember } from "./MemberClaimCodes";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const MEMBERS: ClaimableMember[] = [
  { membership_id: 11, user_id: 21, display_name: "Counter Guest", username: "guest", is_walk_in: true },
  { membership_id: 12, user_id: 22, display_name: "Account Holder", username: "member", is_walk_in: false },
];
const ISSUED = {
  id: 41,
  membership_id: 11,
  member_display_name: "Counter Guest",
  issued_by_id: 7,
  issued_at: "2026-08-16T10:00:00Z",
  expires_at: "2026-08-16T10:15:00Z",
  consumed_at: null,
  revoked_at: null,
  status: "issued" as const,
  code: "MC1-41-ABCD-EFGH-JKMP-QRST",
  qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
};

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
    options?.method === "POST" ? Promise.resolve(ISSUED) : Promise.resolve([]),
  );
});

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemberClaimCodes makerspaceId={7} members={MEMBERS} />
    </QueryClientProvider>,
  );
}

describe("MemberClaimCodes", () => {
  it("offers only walk-ins and renders the one-time code, QR, and expiry", async () => {
    renderPanel();
    await screen.findByText("No active claim codes.");

    expect(screen.getByRole("option", { name: "Counter Guest" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Account Holder" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Walk-in member"), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "Issue claim code" }));

    expect(await screen.findByText(ISSUED.code)).toBeVisible();
    expect(screen.getByAltText("Claim code QR for Counter Guest")).toHaveAttribute(
      "src",
      expect.stringContaining("data:image/svg+xml"),
    );
    expect(screen.getByText(/Expires .*This code will not be shown again/i)).toBeVisible();
    expect(screen.getByText(/never email or text it/i)).toBeVisible();
    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/makerspaces/7/member-claim-codes",
        { method: "POST", body: JSON.stringify({ membership_id: 11 }) },
      ),
    );
  });
});

