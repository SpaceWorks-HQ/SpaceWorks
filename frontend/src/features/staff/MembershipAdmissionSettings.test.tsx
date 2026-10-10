import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import type { AdmissionSettings } from "../members/membershipAdmissionApi";
import { admissionRecipeDraft, MembershipAdmissionSettings } from "./MembershipAdmissionSettings";
import { expectNoA11yViolations } from "../../test/axe";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));
const settings: AdmissionSettings = {
  join_mode: "approval", vouches_required: 1, voucher_min_tenure_days: 30, voucher_pending_limit: 3,
  vouch_expiry_days: 30, vouch_replaces_approval: false, payment_timing: "after_activation", application_schema: null,
  default_plan: 2, joining_fee: "5.00", joining_fee_currency: "usd", rejoin_dues_rule: "once", request_expiry_days: 30,
};
beforeEach(() => { vi.mocked(staffRequest).mockReset(); });

describe("admission settings recipes", () => {
  it.each(["free_open", "free_vouch"] as const)("prefills %s without retained pricing", (recipe) => {
    const result = admissionRecipeDraft(settings, recipe);
    expect(result.default_plan).toBeNull(); expect(result.joining_fee).toBe("0.00");
    expect(result.join_mode).toBe(recipe === "free_open" ? "open" : "vouch");
    expect(result.voucher_min_tenure_days).toBe(30); expect(result.voucher_pending_limit).toBe(3);
    expect(result.vouch_replaces_approval).toBe(false);
  });
  it.each(["paid_approval", "paid_invite_only"] as const)("retains the selected plan for %s and requires payment first", (recipe) => {
    const result = admissionRecipeDraft(settings, recipe);
    expect(result.default_plan).toBe(2); expect(result.payment_timing).toBe("before_activation");
    expect(result.join_mode).toBe(recipe === "paid_approval" ? "approval" : "invite_only");
  });
  it("lets a manager edit a recipe before saving and refreshes member state", async () => {
    vi.mocked(staffRequest).mockImplementation((path, options) => Promise.resolve(options?.method === "PATCH" ? { ...settings, ...JSON.parse(String(options.body)) } : path.endsWith("/membership-admission") ? settings : [{ id: 2, name: "Maker", amount: "25.00", currency: "usd", is_active: true }]) as ReturnType<typeof staffRequest>);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["member", "memberships"], {});
    const view = render(<QueryClientProvider client={client}><MembershipAdmissionSettings makerspaceId={7} /></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText("Admission recipe"), { target: { value: "free_vouch" } });
    expect(screen.getByLabelText("Joining fee")).toHaveValue(0);
    fireEvent.change(screen.getByLabelText("Vouches required"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save admission settings" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Admission settings saved.");
    const patch = vi.mocked(staffRequest).mock.calls.find(([, options]) => options?.method === "PATCH")!;
    expect(patch[0]).toBe("/admin/makerspaces/7/membership-admission");
    expect(JSON.parse(String(patch[1]?.body))).toMatchObject({ recipe: "free_vouch", vouches_required: 2, join_mode: "vouch", default_plan: null });
    await waitFor(() => expect(client.getQueryState(["member", "memberships"])?.isInvalidated).toBe(true));
    await expectNoA11yViolations(view.container);
  });
});
