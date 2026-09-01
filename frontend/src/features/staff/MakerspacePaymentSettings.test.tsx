import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MakerspacePaymentSettings } from "./MakerspacePaymentSettings";
import type { Makerspace } from "./StaffPanels";


const { query, staffRequest } = vi.hoisted(() => ({
  query: vi.fn(),
  staffRequest: vi.fn(),
}));

vi.mock("../../lib/api", () => ({ staffRequest }));

vi.mock("./StaffPanels", async () => {
  const actual = await vi.importActual<typeof import("./StaffPanels")>("./StaffPanels");
  return { ...actual, useStaffGet: query };
});

function renderSettings(
  platformHosting: boolean,
  publishableKeySet = false,
  isLoading = false,
) {
  query.mockReturnValue({
    data: isLoading ? undefined : {
      default_currency: "usd",
      stripe_publishable_key: "pk_stored_never_returned",
      stripe_secret_key_set: false,
      stripe_webhook_secret_set: false,
      stripe_publishable_key_set: publishableKeySet,
      effective_mode: platformHosting ? "connect" : "unavailable",
      connect_status: platformHosting ? "active" : "unconnected",
      connect_charges_enabled: platformHosting,
      connect_payouts_enabled: platformHosting,
    },
    isLoading,
    error: null,
  });
  const makerspace = {
    id: 7,
    name: "Community Lab",
    platform_hosting: platformHosting,
  } as Makerspace;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MakerspacePaymentSettings makerspace={makerspace} />
    </QueryClientProvider>,
  );
}

describe("MakerspacePaymentSettings", () => {
  it("disables payment actions while settings are loading", () => {
    renderSettings(false, false, true);

    expect(
      screen.getByRole("button", { name: /save payment settings/i }),
    ).toBeDisabled();
  });

  it("keeps self-host raw-only and shows managed Connect onboarding", () => {
    const view = renderSettings(false);
    expect(screen.getByText("Stripe payments")).toBeTruthy();
    expect(screen.getByLabelText("Stripe secret key")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /connect stripe/i })).toBeNull();

    view.unmount();
    renderSettings(true);
    expect(screen.getByRole("button", { name: /connect stripe/i })).toBeTruthy();
    expect(
      screen.getByText(/complete raw credential pair takes precedence over connect/i),
    ).toBeTruthy();
    expect(screen.getByText(/active/i)).toBeTruthy();
  });

  it("submits a new publishable key without rendering a stored value", async () => {
    staffRequest.mockResolvedValue({});
    renderSettings(false, true);

    const input = screen.getByPlaceholderText("Stripe publishable key set");
    expect(input).toHaveValue("");
    expect(screen.queryByDisplayValue("pk_stored_never_returned")).toBeNull();
    fireEvent.change(input, { target: { value: "pk_test_new" } });
    fireEvent.click(screen.getByRole("button", { name: /save payment settings/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    const lastCall = staffRequest.mock.calls[staffRequest.mock.calls.length - 1];
    const body = JSON.parse(lastCall[1]?.body as string);
    expect(body.stripe_publishable_key).toBe("pk_test_new");

    const clearButton = screen.getByRole("button", { name: /clear raw configuration/i });
    await waitFor(() => expect(clearButton).not.toBeDisabled());
    fireEvent.click(clearButton);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
    const clearCall = staffRequest.mock.calls[1];
    const clearBody = JSON.parse(clearCall[1]?.body as string);
    expect(clearBody.stripe_publishable_key).toBe("");
  });
});
