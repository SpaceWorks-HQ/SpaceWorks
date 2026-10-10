import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PaymentsPanel } from "./PaymentsPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual("../../lib/api"), staffRequest }));

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue([{
    id: 1, subject_type: "booking", subject_id: 1, subject_label: "Room charge",
    status: "pending", amount: "12.00", currency: "usd", refunded_amount: "0.00",
    refunds: [], settlement: null, created_at: "2026-10-10T10:00:00Z", updated_at: "2026-10-10T10:00:00Z",
  }]);
});

function panel(actions: string[]) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <PaymentsPanel makerspaceId={7} actorActions={actions} />
  </QueryClientProvider>);
}

describe("finance console controls", () => {
  it("renders the ledger without mutation controls for a read-only treasurer", async () => {
    panel(["view_finance"]);
    await screen.findByText("Room charge");
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments?status=pending");
    expect(screen.queryByRole("button", { name: "Mark offline" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Waive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refund" })).not.toBeInTheDocument();
  });

  it("uses counter scope and offers receipt recording to a cashier", async () => {
    panel(["record_payment"]);
    await screen.findByText("Room charge");
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments?for_recording=true&status=pending");
    expect(screen.getByRole("button", { name: "Mark offline" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Waive" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Paid online" })).not.toBeInTheDocument();
  });
});
