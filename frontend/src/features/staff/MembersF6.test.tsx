import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersPanel } from "./MembersPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual("../../lib/api"), staffRequest }));

function panel(finance = false, recording = false) {
  render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MembersPanel makerspaceId={7} membershipEnabled canManageMakerspace={false}
      canViewFinance={finance} canRecordPayment={recording} />
  </QueryClientProvider></MemoryRouter>);
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((url: string) => {
    if (url.startsWith("/admin/memberships?")) return Promise.resolve({ results: [{
      id: 1, status: "active", user: { id: 2, username: "staff", display_name: "Staff member" },
      assigned_role: { id: 9, name: "Inventory staff" }, verified_at: null,
      can_refer: false, can_verify: false, waiver_required: false,
      payment: { id: 3, status: "pending", amount: "12.00", currency: "usd" },
    }], count: 1, next: null, previous: null });
    if (url.startsWith("/admin/membership-requests?")) return Promise.resolve({ results: [{
      id: 4, kind: "invite", state: "invited", invite_email: "staff@example.test",
      user: { id: 5, username: "invited" }, assigned_role: { id: 9, name: "Inventory staff" },
    }], count: 1, next: null, previous: null });
    if (url.endsWith("/roles")) return Promise.resolve([{ id: 6, name: "Member" }]);
    return Promise.resolve([]);
  });
});

describe("coordinator roster controls", () => {
  it("keeps verification available on staff rows without exposing staff-role mutations", async () => {
    panel();
    await screen.findByText("Staff member");
    await screen.findByText(/invited · invite/);
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/memberships/1/verify", { method: "POST" }));
    expect(screen.queryByLabelText("Role for Staff member")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel invitation" })).not.toBeInTheDocument();
    expect(screen.queryByText("Payment $12.00")).not.toBeInTheDocument();
  });

  it("shows money without mutation controls when the coordinator also holds view_finance", async () => {
    panel(true);
    await screen.findByText("Payment $12.00");
    expect(screen.queryByRole("button", { name: "Mark offline" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Waive" })).not.toBeInTheDocument();
  });

  it("offers cash recording without waiving when the coordinator holds both money actions", async () => {
    panel(true, true);
    await screen.findByRole("button", { name: "Mark offline" });
    expect(screen.queryByRole("button", { name: "Waive" })).not.toBeInTheDocument();
  });
});
