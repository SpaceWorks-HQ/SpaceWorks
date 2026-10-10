import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { MemberPaymentRows, type MemberPayment } from "./MemberPayments";

it("shows a member the refunded amount on an offline deposit", () => {
  const payment: MemberPayment = {
    id: 1, subject_type: "loan_deposit", subject_label: "Loan deposit", status: "paid_offline",
    amount: "10.00", currency: "usd", refunded_amount: "6.00", checkout_url: "",
    online_payment_available: false, settlement: null, created_at: "2026-01-01T10:00:00Z",
  };
  render(<MemberPaymentRows payments={[payment]} onCheckout={vi.fn()} />);
  expect(screen.getByText("Refunded 6.00 USD")).toBeVisible();
});
