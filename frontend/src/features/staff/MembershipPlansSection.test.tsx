import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../test/axe";
import { MembershipPlansSection, validatePlanForm } from "./MembershipPlansSection";
import { MemberTermsDialog } from "./MemberTermsDialog";
import type { MembershipPlan, MembershipTerm } from "./membershipPlansApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const plans: MembershipPlan[] = [
  { id: 1, name: "Monthly maker", interval: "monthly", custom_days: null, amount: "30.00", currency: "usd", is_active: true, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" },
  { id: 2, name: "Summer pass", interval: "custom_days", custom_days: 90, amount: "75.00", currency: "usd", is_active: false, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" },
];

const terms: MembershipTerm[] = [
  { id: 5, membership: 11, plan: 1, plan_name: "Monthly maker", starts_at: "2026-08-01T00:00:00Z", ends_at: "2026-09-01T00:00:00Z", status: "active", renewal_payment: 3, created_by: 1, created_at: "2026-08-01T00:00:00Z" },
  { id: 4, membership: 11, plan: 1, plan_name: "Monthly maker", starts_at: "2026-07-01T00:00:00Z", ends_at: "2026-08-01T00:00:00Z", status: "expired", renewal_payment: 2, created_by: 1, created_at: "2026-07-01T00:00:00Z" },
];

function route(path: string, options?: RequestInit) {
  if (options?.method === "POST" || options?.method === "PATCH") return Promise.resolve({ ...plans[0], id: 9 });
  if (path.endsWith("/membership-plans")) return Promise.resolve(plans);
  if (path.endsWith("/terms")) return Promise.resolve(terms);
  return Promise.resolve([]);
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(route);
});

describe("MembershipPlansSection", () => {
  it("lists plans with their interval and price and creates a new one", async () => {
    const { container } = wrap(<MembershipPlansSection makerspaceId={7} />);

    expect(await screen.findByText("Monthly maker")).toBeVisible();
    expect(screen.getByText(/Every 90 days/)).toBeVisible();
    expect(screen.getByText("Inactive")).toBeVisible();

    fireEvent.change(screen.getByRole("textbox", { name: "Plan name" }), { target: { value: "Yearly" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Interval" }), { target: { value: "yearly" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Amount" }), { target: { value: "300" } });
    fireEvent.click(screen.getByRole("button", { name: "Create plan" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7/membership-plans",
      {
        method: "POST",
        body: JSON.stringify({ name: "Yearly", interval: "yearly", custom_days: null, amount: "300", currency: "usd", is_active: true }),
      },
    ));

    await expectNoA11yViolations(container);
  });

  it("edits an existing plan through PATCH and toggles activity", async () => {
    wrap(<MembershipPlansSection makerspaceId={7} />);
    await screen.findByText("Monthly maker");

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[1]);
    expect(screen.getByRole("form", { name: "Edit plan Summer pass" })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: /Custom days/ }), { target: { value: "120" } });
    fireEvent.click(screen.getByRole("button", { name: "Save plan" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-plans/2",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"custom_days":120') }),
    ));

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-plans/1",
      { method: "PATCH", body: JSON.stringify({ is_active: false }) },
    ));
  });

  it("validates like the serializer", () => {
    const base = { name: "x", interval: "monthly" as const, custom_days: "", amount: "1.00", currency: "usd", is_active: true };
    expect(validatePlanForm(base)).toBeNull();
    expect(validatePlanForm({ ...base, interval: "custom_days" })).toMatch(/whole number of days/);
    expect(validatePlanForm({ ...base, currency: "dollars" })).toMatch(/ISO 4217/);
    expect(validatePlanForm({ ...base, amount: "1.999" })).toMatch(/two decimals/);
  });
});

describe("MemberTermsDialog", () => {
  it("shows the member's terms, starts a new one on the chosen plan and cancels the active one", async () => {
    const onClose = vi.fn();
    const { container } = wrap(
      <MemberTermsDialog makerspaceId={7} membershipId={11} memberName="Ada Lovelace" onClose={onClose} />,
    );

    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(await screen.findByText("expired")).toBeVisible();
    // Only the active plan is offered; the inactive Summer pass is not.
    expect(screen.getByRole("combobox", { name: "Plan" })).not.toHaveTextContent("Summer pass");

    fireEvent.click(screen.getByRole("button", { name: "Start term" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/memberships/11/terms",
      { method: "POST", body: JSON.stringify({ plan_id: 1 }) },
    ));

    fireEvent.click(screen.getByRole("button", { name: "Cancel term" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-terms/5/cancel",
      { method: "POST" },
    ));

    await expectNoA11yViolations(container);
  });
});
