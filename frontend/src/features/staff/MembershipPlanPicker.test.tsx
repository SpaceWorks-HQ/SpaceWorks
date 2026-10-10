import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { listPlans } from "./membershipPlansApi";
import { MembershipPlanPicker } from "./MembershipPlanPicker";
vi.mock("./membershipPlansApi", async () => ({ ...await vi.importActual("./membershipPlansApi"), listPlans: vi.fn() }));
function show() {
  const change = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MembershipPlanPicker makerspaceId={3} value={null} onChange={change} /></QueryClientProvider>);
  return change;
}
describe("MembershipPlanPicker", () => {
  it("offers active plans and leaves no plan as the default", async () => {
    vi.mocked(listPlans).mockResolvedValue([{ id: 8, name: "Monthly", amount: "5", currency: "usd", is_active: true }, { id: 9, name: "Retired", is_active: false }] as Awaited<ReturnType<typeof listPlans>>);
    const change = show(); await screen.findByRole("option", { name: /Monthly/ });
    expect(screen.queryByRole("option", { name: /Retired/ })).toBeNull();
    fireEvent.change(screen.getByLabelText("Approval plan (optional)"), { target: { value: "8" } }); expect(change).toHaveBeenCalledWith(8);
    fireEvent.change(screen.getByLabelText("Approval plan (optional)"), { target: { value: "" } }); expect(change).toHaveBeenCalledWith(null);
  });
  it("explains an empty plan list", async () => { vi.mocked(listPlans).mockResolvedValue([]); show(); expect(await screen.findByText(/No active plans/)).toBeVisible(); });
  it("shows a loading state and a failed fetch", async () => { vi.mocked(listPlans).mockRejectedValue(new Error("Plans unavailable")); show(); expect(screen.getByText("Loading approval plans…")).toBeVisible(); expect(await screen.findByRole("alert")).toHaveTextContent("Plans unavailable"); });
});
