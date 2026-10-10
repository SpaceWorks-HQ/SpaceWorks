import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { MemberLoanRenew } from "./MemberLoanRenew";
import { MemberActivityPanel, type MemberActivity } from "./MemberActivity";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest: request, staffRequestBlob: vi.fn() }));
vi.mock("./MemberEventFeedback", () => ({ MemberEventFeedback: () => null }));
vi.mock("./MemberEventCancel", () => ({ MemberEventCancel: () => null }));
vi.mock("./MemberCalendarActions", () => ({ MemberCalendarActions: () => null }));
beforeEach(() => { request.mockReset(); });

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><MemberLoanRenew makerspaceId={7} makerspaceSlug="lab" requestId={12} /></QueryClientProvider>);
  return invalidate;
}

it("renews the owned loan and refreshes member activity", async () => {
  request.mockResolvedValue({ return_due_at: "2026-10-20T00:00:00Z", renewal_count: 1 });
  const invalidate = setup();
  fireEvent.click(screen.getByRole("button", { name: "Renew loan" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/member/makerspaces/7/loans/12/renew", { method: "POST", body: "{}" }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["member", "lab", "activity"] }));
  expect(await screen.findByRole("button", { name: "Loan renewed" })).toBeDisabled();
});

it("shows policy refusal without invalidating cached activity", async () => {
  request.mockRejectedValue(new Error("Another borrower is waiting."));
  const invalidate = setup();
  fireEvent.click(screen.getByRole("button", { name: "Renew loan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Another borrower is waiting.");
  expect(invalidate).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Renew loan" })).toBeEnabled();
});

it("allows another policy-approved renewal after activity refreshes the due date", async () => {
  request.mockResolvedValue({ return_due_at: "2026-10-20T00:00:00Z", renewal_count: 1 });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const activity: MemberActivity = {
    active_hardware_loans: [{ request_id: 12, can_renew: true, label: "Drill",
      checked_out_at: "2026-10-10T00:00:00Z", due_at: "2026-10-13T00:00:00Z", overdue: false }],
    recent_presence_sessions: [], currently_checked_in: false,
    accountability: { membership_active: true, waiver_acceptance_required: false, restriction_code: null },
  };
  const panel = (value: MemberActivity) => <QueryClientProvider client={client}>
    <MemberActivityPanel activity={value} makerspaceId={7} makerspaceSlug="lab" />
  </QueryClientProvider>;
  const view = render(panel(activity));
  fireEvent.click(screen.getByRole("button", { name: "Renew loan" }));
  expect(await screen.findByRole("button", { name: "Loan renewed" })).toBeDisabled();
  view.rerender(panel({ ...activity, active_hardware_loans: [{ ...activity.active_hardware_loans[0],
    due_at: "2026-10-20T00:00:00Z", renewal_count: 1 }] }));
  expect(screen.getByRole("button", { name: "Renew loan" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Renew loan" }));
  await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
});
