import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest } from "../../lib/api";
import { MemberAdmission, MemberVouch } from "./MemberAdmission";

vi.mock("../../lib/api", () => ({ memberRequest: vi.fn() }));
function show(child: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["member", "memberships"], {});
  render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
  return client;
}
beforeEach(() => { vi.mocked(memberRequest).mockReset(); });

describe("member admission progress", () => {
  it("shows pay-before-activate with an offline path and no active-membership claim", async () => {
    vi.mocked(memberRequest).mockResolvedValue({ state: "revoked" });
    const client = show(<MemberAdmission makerspaceId={7} request={{ id: 21, state: "awaiting_payment", admission_payment: { id: 8, status: "pending", amount: "40.00", currency: "usd" }, expires_at: "2026-11-01T12:00:00Z" }} />);
    expect(screen.getByText("Membership awaiting payment")).toBeVisible();
    expect(screen.getByText(/Use the Payments tab, or pay at the space/)).toBeVisible();
    expect(screen.getByText("Admission charge: 40.00 USD · pending")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel application" }));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/7/admission/21/cancel", { method: "POST" }));
    await waitFor(() => expect(client.getQueryState(["member", "memberships"])?.isInvalidated).toBe(true));
  });
  it("provides an application number and immutable vouch identity", () => {
    show(<MemberAdmission makerspaceId={7} request={{ id: 21, state: "awaiting_vouches", vouches: [{ voucher_id: 4, voucher_name: "Sam", created_at: "2026-10-10T12:00:00Z", expires_at: "2026-11-10T12:00:00Z" }] }} />);
    expect(screen.getByText(/Share application number 21/)).toBeVisible();
    expect(screen.getByText(/Vouched by Sam/)).toBeVisible();
  });
  it("renders eligibility refusals and permits a corrected vouch retry", async () => {
    vi.mocked(memberRequest).mockRejectedValueOnce(new Error("Voucher tenure must be at least 30 days.")).mockResolvedValueOnce({});
    show(<MemberVouch makerspaceId={7} />);
    fireEvent.change(screen.getByLabelText("Application number"), { target: { value: "21" } });
    fireEvent.submit(screen.getByRole("button", { name: "Record my vouch" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Voucher tenure must be at least 30 days.");
    fireEvent.submit(screen.getByRole("button", { name: "Record my vouch" }).closest("form")!);
    expect(await screen.findByRole("status")).toHaveTextContent("Your vouch is recorded.");
    expect(memberRequest).toHaveBeenLastCalledWith("/member/makerspaces/7/admission/21/vouch", { method: "POST" });
  });
});
