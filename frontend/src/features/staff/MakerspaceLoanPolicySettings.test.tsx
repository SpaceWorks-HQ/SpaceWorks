import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { MakerspaceLoanPolicySettings, type LoanPolicy } from "./MakerspaceLoanPolicySettings";

const { query, request } = vi.hoisted(() => ({ query: vi.fn(), request: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest: request }));
vi.mock("./panels/shared", () => ({ useStaffGet: query }));
const policy: LoanPolicy = {
  id: 7, default_loan_days: 7, loan_renewal_mode: "off", loan_max_renewals: 1,
  loan_renewal_days: 7, loan_max_active: 0, loan_max_items: 0,
  loan_reminder_offsets_hours: [0], loan_escalate_overdue_days: 0,
};
beforeEach(() => {
  query.mockReset(); request.mockReset();
  query.mockReturnValue({ data: policy, error: null });
});
function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><MakerspaceLoanPolicySettings makerspaceId={7} /></QueryClientProvider>);
  return invalidate;
}

it("saves the policy with signed offsets and refreshes settings", async () => {
  request.mockResolvedValue(policy);
  const invalidate = setup();
  fireEvent.change(screen.getByLabelText("Renewal mode"), { target: { value: "auto" } });
  fireEvent.change(screen.getByLabelText(/Reminder offsets in hours/), { target: { value: "-24, 0, 48" } });
  fireEvent.click(screen.getByRole("button", { name: "Save loan policy" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspace/7/return-policy", {
    method: "PATCH", body: JSON.stringify({ ...policy, loan_renewal_mode: "auto", loan_reminder_offsets_hours: [-24, 0, 48] }),
  }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["staff", "loan-policy", 7] }));
});

it("rejects duplicated offsets before making a request", () => {
  setup();
  fireEvent.change(screen.getByLabelText(/Reminder offsets in hours/), { target: { value: "0, 0" } });
  fireEvent.click(screen.getByRole("button", { name: "Save loan policy" }));
  expect(screen.getByRole("alert")).toHaveTextContent("unique whole-hour offsets");
  expect(request).not.toHaveBeenCalled();
});

it("shows a scoped or module gate error", () => {
  query.mockReturnValue({ data: undefined, error: new Error("request_workflow is disabled") });
  setup();
  expect(screen.getByRole("alert")).toHaveTextContent("request_workflow is disabled");
});
