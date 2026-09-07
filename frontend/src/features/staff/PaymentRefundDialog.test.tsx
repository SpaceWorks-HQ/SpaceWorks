import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";
import { PaymentRefundDialog, validateRefundAmount } from "./PaymentRefundDialog";
import { refundErrorMessage, remainingRefundable, type PaymentRow } from "./paymentsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const payment: PaymentRow = {
  id: 41,
  subject_type: "booking",
  subject_id: 9,
  subject_label: "Laser cutter booking",
  status: "paid_online",
  amount: "100.00",
  currency: "usd",
  refunded_amount: "20.00",
  refunds: [
    { id: 1, amount: "20.00", currency: "usd", status: "succeeded", reason: "Overcharge", created_at: "2026-08-01T10:00:00Z", settled_at: "2026-08-01T10:00:05Z" },
    { id: 2, amount: "10.00", currency: "usd", status: "pending", reason: "", created_at: "2026-08-02T10:00:00Z", settled_at: null },
    { id: 3, amount: "5.00", currency: "usd", status: "failed", reason: "", created_at: "2026-08-03T10:00:00Z", settled_at: "2026-08-03T10:00:05Z" },
  ],
  created_at: "2026-07-20T10:00:00Z",
  updated_at: "2026-07-20T10:00:00Z",
};

function renderDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const onClose = vi.fn();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <PaymentRefundDialog makerspaceId={7} payment={payment} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { ...view, invalidate, onClose };
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ ...payment, refunded_amount: "90.00" });
});

describe("PaymentRefundDialog", () => {
  it("counts pending and succeeded refunds against the balance, never failed ones", () => {
    expect(remainingRefundable(payment)).toBe(70);
    expect(validateRefundAmount("70.00", 70)).toBeNull();
    expect(validateRefundAmount("70.01", 70)).toMatch(/exceed/);
    expect(validateRefundAmount("0", 70)).toMatch(/greater than zero/);
    expect(validateRefundAmount("1.234", 70)).toMatch(/two decimals/);
  });

  it("lists the refunds, defaults the amount to the remaining balance and posts the refund", async () => {
    const { container, invalidate, onClose } = renderDialog();

    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByText("Overcharge", { exact: false })).toBeVisible();
    expect(screen.getByText("pending")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Refund amount" })).toHaveValue("70.00");

    fireEvent.change(screen.getByRole("textbox", { name: "Refund amount" }), { target: { value: "25.50" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Reason (optional)" }), { target: { value: "Damaged on arrival" } });
    fireEvent.click(screen.getByRole("button", { name: "Send refund" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/41/refund",
      { method: "POST", body: JSON.stringify({ amount: "25.50", reason: "Damaged on arrival" }) },
    ));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["payments", 7] });

    await expectNoA11yViolations(container);
  });

  it("refuses an over-balance amount locally without calling the API", () => {
    renderDialog();

    fireEvent.change(screen.getByRole("textbox", { name: "Refund amount" }), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Send refund" }));

    expect(screen.getByText("Refund amount cannot exceed the remaining balance.")).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("turns the backend refund codes into readable messages", async () => {
    staffRequest.mockRejectedValue(new StructuredApiError(502, { detail: "The payment provider rejected the refund.", code: "refund_provider_failed" }));
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Send refund" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The payment provider rejected the refund. No money was sent back");
    expect(refundErrorMessage(new StructuredApiError(400, { code: "refund_not_online" }))).toMatch(/settled online/);
    expect(refundErrorMessage(new StructuredApiError(400, { code: "refund_exceeds_balance" }))).toMatch(/remaining refundable balance/);
    expect(refundErrorMessage(new StructuredApiError(400, { code: "refund_amount_invalid" }))).toMatch(/greater than zero/);
    expect(refundErrorMessage(new StructuredApiError(403, { detail: "Permission denied." }))).toBe("Permission denied.");
  });
});
