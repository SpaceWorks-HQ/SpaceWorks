import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AdmissionJoin } from "./AdmissionJoin";
import type { JoinMode, PublicAdmission } from "./membershipAdmissionApi";
import { expectNoA11yViolations } from "../../test/axe";

const settings: PublicAdmission = {
  join_mode: "approval", vouches_required: 1, payment_timing: "after_activation",
  application_schema: [{ id: "motivation", label: "Why join?", type: "paragraph", options: [], required: true }],
  default_plan: null, joining_fee: "0.00",
};

describe("admission join conditions", () => {
  it.each(["open", "approval", "invite_only", "vouch", "closed"] as JoinMode[])("shows the %s entry mode", (mode) => {
    render(<AdmissionJoin settings={{ ...settings, join_mode: mode }} signedIn pending={false} onJoin={vi.fn()} onSignIn={vi.fn()} />);
    if (mode === "closed" || mode === "invite_only") expect(screen.queryByRole("button")).toBeNull();
    else expect(screen.getByLabelText(/Why join/)).toBeVisible();
    if (mode === "vouch") expect(screen.getByText(/1 member vouch/)).toBeVisible();
  });
  it.each(["after_activation", "before_activation"] as const)("explains paid open activation with %s", (payment_timing) => {
    render(<AdmissionJoin settings={{ ...settings, join_mode: "open", payment_timing, default_plan: { id: 1, name: "Community", amount: "10.00", currency: "usd" } }} signedIn pending={false} onJoin={vi.fn()} onSignIn={vi.fn()} />);
    expect(screen.getByText("Plan: Community · 10.00 USD")).toBeVisible();
    expect(screen.getByRole("button", { name: payment_timing === "before_activation" ? "Apply to join" : "Join instantly" })).toBeVisible();
    if (payment_timing === "before_activation") expect(screen.getByText(/pay online when available, or at the space/)).toBeVisible();
  });
  it("collects application answers before submitting", () => {
    const join = vi.fn();
    render(<AdmissionJoin settings={settings} signedIn pending={false} onJoin={join} onSignIn={vi.fn()} />);
    fireEvent.submit(screen.getByRole("button", { name: "Request to join" }).closest("form")!);
    expect(join).not.toHaveBeenCalled();
    expect(screen.getByText("This question is required.")).toBeVisible();
    fireEvent.change(screen.getByLabelText(/Why join/), { target: { value: "Learn woodworking" } });
    fireEvent.submit(screen.getByRole("button", { name: "Request to join" }).closest("form")!);
    expect(join).toHaveBeenCalledWith({ motivation: "Learn woodworking" });
  });
  it("offers sign-in without exposing a submit action to anonymous applicants", () => {
    const signIn = vi.fn();
    render(<AdmissionJoin settings={settings} signedIn={false} pending={false} onJoin={vi.fn()} onSignIn={signIn} />);
    fireEvent.click(screen.getByRole("button", { name: "Sign in to join" }));
    expect(signIn).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText(/Why join/)).toBeNull();
  });
  it("keeps admission questions and actions accessible", async () => {
    const view = render(<AdmissionJoin settings={settings} signedIn pending={false} onJoin={vi.fn()} onSignIn={vi.fn()} />);
    await expectNoA11yViolations(view.container);
  });
});
