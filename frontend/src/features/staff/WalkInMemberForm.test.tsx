import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { WalkInMemberForm } from "./WalkInMemberForm";
import type { PublicAdmission } from "../members/membershipAdmissionApi";
import { expectNoA11yViolations } from "../../test/axe";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(), staffRequest: vi.fn() }));
const settings: PublicAdmission = { join_mode: "open", vouches_required: 1, application_schema: null, payment_timing: "after_activation", default_plan: null, joining_fee: "0.00" };
function show() {
  const created = vi.fn();
  const view = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><WalkInMemberForm makerspaceId={7} onCreated={created} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Not a member yet? Add a walk-in" }));
  return { created, ...view };
}
beforeEach(() => { vi.mocked(staffRequest).mockReset(); });
describe("walk-in admission gates", () => {
  it("selects an active walk-in only after the borrower list refreshes", async () => {
    vi.mocked(staffRequest).mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { user_id: 8, display_name: "Jo", username: "walkin_jo" } : settings) as ReturnType<typeof staffRequest>);
    const { created } = show();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jo" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Add walk-in" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
    await waitFor(() => expect(created).toHaveBeenCalledWith(8));
  });
  it("keeps an awaiting-payment applicant out of the handout selection", async () => {
    vi.mocked(staffRequest).mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { user_id: 8, display_name: "Jo", username: "walkin_jo", admission_request: { id: 21, state: "awaiting_payment", admission_payment: { id: 9, amount: "25.00", currency: "usd", status: "pending" } } } : { ...settings, payment_timing: "before_activation" }) as ReturnType<typeof staffRequest>);
    const { created } = show();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jo" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Add walk-in" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Walk-in application #21 · awaiting payment");
    expect(screen.getByText(/record payment with a receipt/)).toBeVisible();
    expect(screen.getByText("Admission charge: 25.00 USD")).toBeVisible();
    expect(created).not.toHaveBeenCalled();
  });
  it("validates and sends staff-collected application answers for a vouch applicant", async () => {
    const schema = [{ id: "why", label: "Why join?", type: "paragraph", options: [], required: true }];
    vi.mocked(staffRequest).mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { user_id: 8, display_name: "Jo", username: "walkin_jo", admission_request: { id: 21, state: "awaiting_vouches" } } : { ...settings, join_mode: "vouch", application_schema: schema }) as ReturnType<typeof staffRequest>);
    const { created, container } = show();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jo" } });
    await screen.findByLabelText(/Why join/);
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
    expect(screen.getByText("This question is required.")).toBeVisible();
    expect(vi.mocked(staffRequest).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    fireEvent.change(screen.getByLabelText(/Why join/), { target: { value: "Learn woodworking" } });
    await expectNoA11yViolations(container);
    fireEvent.click(screen.getByRole("button", { name: "Add walk-in" }));
    expect(await screen.findByRole("status")).toHaveTextContent("awaiting vouches");
    const post = vi.mocked(staffRequest).mock.calls.find(([, options]) => options?.method === "POST")!;
    expect(JSON.parse(String(post[1]?.body))).toMatchObject({ application_answers: { why: "Learn woodworking" } });
    expect(created).not.toHaveBeenCalled();
  });
  it("refuses creation in closed mode", async () => {
    vi.mocked(staffRequest).mockResolvedValue({ ...settings, join_mode: "closed" });
    show(); fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jo" } });
    expect(await screen.findByText("Membership applications are closed.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Add walk-in" })).toBeDisabled();
  });
  it("keeps creation disabled when admission conditions could not be loaded", async () => {
    vi.mocked(staffRequest).mockRejectedValue(new Error("Unable to load admission conditions."));
    show(); fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jo" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load admission conditions.");
    expect(screen.getByRole("button", { name: "Add walk-in" })).toBeDisabled();
  });
});
