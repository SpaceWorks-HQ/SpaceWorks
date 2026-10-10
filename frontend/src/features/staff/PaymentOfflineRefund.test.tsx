import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../test/axe";
import { PaymentRefundDialog } from "./PaymentRefundDialog";
import { PaymentsPanel } from "./PaymentsPanel";
import type { PaymentRow } from "./paymentsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const payment: PaymentRow = {
  id: 41, subject_type: "loan_deposit", subject_id: 9, subject_label: "Loan deposit",
  status: "paid_offline", amount: "100.00", currency: "inr", refunded_amount: "0.00",
  refunds: [], created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z",
};

function mount(dialog = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const onClose = vi.fn();
  const view = render(<MemoryRouter><QueryClientProvider client={queryClient}>
    {dialog ? <PaymentRefundDialog makerspaceId={7} payment={payment} onClose={onClose} /> : <PaymentsPanel makerspaceId={7} actorActions={["view_finance", "record_payment", "manage_bookings", "manage_makerspace"]} />}
  </QueryClientProvider></MemoryRouter>);
  return { ...view, invalidate, onClose };
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => options?.method === "POST" ? payment : { count: 1, next: null, previous: null, results: [payment] });
});

describe("Offline refunds", () => {
  it("records method, reference and return date through the core endpoint and refreshes reports", async () => {
    const { container, invalidate, onClose } = mount();
    fireEvent.change(screen.getByRole("combobox", { name: "Refund method" }), { target: { value: "upi" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Refund reference (optional)" }), { target: { value: "upi-123" } });
    fireEvent.change(screen.getByLabelText("Returned at"), { target: { value: "2026-01-01T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Record refund" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/41/refund-offline",
      { method: "POST", body: JSON.stringify({ amount: "100.00", reason: "", receipt: {
        method: "upi", reference: "upi-123", refunded_at: new Date("2026-01-01T10:00").toISOString(),
      } }) },
    ));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["payments", 7] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["operations-report", "payment-reconciliation"] });
    await expectNoA11yViolations(container);
  });

  it("rejects future return dates before recording any money", () => {
    mount();
    fireEvent.change(screen.getByLabelText("Returned at"), { target: { value: "2099-01-01T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Record refund" }));
    expect(screen.getByText(/without a future date/)).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("offers a refund action for a paid-offline loan deposit in the staff ledger", async () => {
    mount(false);
    fireEvent.click(await screen.findByRole("button", { name: "Refund" }));
    expect(screen.getByRole("button", { name: "Record refund" })).toBeVisible();
    expect(screen.getByText(/money already returned/)).toBeVisible();
  });
});
