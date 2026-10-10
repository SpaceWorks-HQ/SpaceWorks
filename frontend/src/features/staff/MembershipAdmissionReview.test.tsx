import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MembershipAdmissionReview, type ReviewMembershipRequest } from "./MembershipAdmissionReview";

const row: ReviewMembershipRequest = {
  id: 21, state: "awaiting_payment", kind: "request", invite_email: "", user: { id: 2, username: "applicant", email: "applicant@example.test" }, assigned_role: null, created_at: "2026-10-10T12:00:00Z",
  application_answers: { version: 1, answers: [{ id: "why", label: "Why join?", type: "paragraph", value: "Build a chair" }] },
  vouches: [{ voucher_id: 4, voucher_name: "Sam", created_at: "2026-10-10T12:00:00Z", expires_at: "2026-11-10T12:00:00Z" }],
  admission_payment: { id: 8, status: "pending", amount: "25.00", currency: "usd" },
};
function show(canViewFinance = false, canRecordPayment = false) {
  render(<QueryClientProvider client={new QueryClient()}><MembershipAdmissionReview row={row} makerspaceId={7} manageable canViewFinance={canViewFinance} canRecordPayment={canRecordPayment} canWaive={false} approvePending={false} declinePending={false} selectedRole={1} onApprove={vi.fn()} onDecline={vi.fn()} /></QueryClientProvider>);
}
describe("membership admission review", () => {
  it("shows the answer snapshot and named vouchers while preventing repeat approval", () => {
    show(); expect(screen.getByText("Build a chair")).toBeInTheDocument(); expect(screen.getByText(/Sam · recorded/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cancel application" })).toBeVisible();
    expect(screen.queryByText("Payment $25.00")).toBeNull();
  });
  it("exposes receipt-based offline settlement only with finance recording authority", () => {
    show(true, true); expect(screen.getByRole("button", { name: "Mark offline" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Waive" })).toBeNull();
  });
});
