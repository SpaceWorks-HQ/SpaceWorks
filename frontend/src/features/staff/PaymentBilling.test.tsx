import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemberPaymentRows, type MemberPayment } from "../members/MemberPayments";
import { PaymentsPanel } from "./PaymentsPanel";
import { PaymentRefundDialog } from "./PaymentRefundDialog";
import { RefundReceiptAmendDialog } from "./RefundReceiptAmendDialog";
import { remainingRefundable, type PaymentRow } from "./paymentsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), staffRequest,
}));

const row: PaymentRow = {
  id: 41, subject_type: "loan_deposit", subject_id: 9, subject_label: "Loan deposit",
  status: "pending", amount: "10.00", currency: "usd", refunded_amount: "0.00", refunds: [],
  due_date: "2026-10-10", due_at: "2026-10-11T01:00:00Z", due_state: "overdue",
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};

function mount(element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<MemoryRouter><QueryClientProvider client={client}>{element}</QueryClientProvider></MemoryRouter>);
}

beforeEach(() => {
  window.history.replaceState({}, "", "/");
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => options?.method === "POST" ? row : { count: 1, next: null, previous: null, results: [row] });
});

describe("Billing due dates and refunds", () => {
  it("displays the server's local day and queries staff overdue filters", async () => {
    mount(<PaymentsPanel makerspaceId={7} actorActions={["view_finance", "record_payment"]} />);
    expect(await screen.findByText("Overdue · 2026-10-10")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "overdue" } });
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments?status=pending&due_state=overdue&page=1&ordering=due_at"));
  });

  it("filters member rows without recomputing dates in the browser timezone", () => {
    const payment: MemberPayment = { ...row, refunded_amount: 0, checkout_url: "", online_payment_available: false, settlement: null };
    render(<MemberPaymentRows payments={[payment, { ...payment, id: 42, subject_label: "Future fee", due_state: "upcoming", due_date: "2026-10-15" }]} onCheckout={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox", { name: "Payment due dates" }), { target: { value: "overdue" } });
    expect(screen.getByText("Overdue · 2026-10-10")).toBeVisible();
    expect(screen.queryByText("Future fee")).not.toBeInTheDocument();
  });

  it("clears pending aging when staff switch to a settled status", async () => {
    mount(<PaymentsPanel makerspaceId={7} actorActions={["view_finance", "record_payment"]} />);
    await screen.findByText("Overdue · 2026-10-10");
    fireEvent.change(screen.getByRole("combobox", { name: "Due" }), { target: { value: "overdue" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Status" }), { target: { value: "paid_offline" } });
    expect(screen.getByRole("combobox", { name: "Due" })).toHaveValue("");
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments?status=paid_offline&page=1&ordering=due_at"));
  });

  it("records a deposit release through the dedicated core route", async () => {
    mount(<PaymentRefundDialog makerspaceId={7} payment={{ ...row, status: "paid_offline" }} releaseDeposit onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Returned at"), { target: { value: "2026-01-01T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Record deposit release" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments/41/release-deposit", expect.objectContaining({ method: "POST" })));
  });

  it("corrects a refund receipt without sending a second amount", async () => {
    const refund = { id: 5, amount: "4.00", currency: "usd", status: "succeeded" as const,
      provider: "manual" as const, method: "cash", reference: "wrong", reason: "", created_at: row.created_at,
      settled_at: row.created_at, refunded_at: row.created_at };
    mount(<RefundReceiptAmendDialog makerspaceId={7} paymentId={41} refund={refund} onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Refund reference"), { target: { value: "correct" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/payments/41/refunds/5/amend", expect.objectContaining({ method: "POST" })));
    const body = JSON.parse(staffRequest.mock.calls[0][1].body);
    expect(body.receipt.reference).toBe("correct");
    expect(body.amount).toBeUndefined();
    expect(remainingRefundable({ amount: "10.00", refunds: [{ ...refund, corrected: true }, { ...refund, id: 6, amends: 5 }] })).toBe(6);
  });
});
