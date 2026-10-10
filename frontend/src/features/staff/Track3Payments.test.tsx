import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BookableSpaceForm, EMPTY_SPACE_FORM } from "./BookableSpaceForm";
import { MakerspaceMembershipSettings } from "./MakerspaceMembershipSettings";
import { PaymentReconcileActions } from "./PaymentReconcileActions";
import type { Makerspace } from "./StaffPanels";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

function wrapper(client = new QueryClient()) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({});
});

describe("Track 3 staff payments", () => {
  it("submits a booking price from the bookable-space editor", () => {
    const submit = vi.fn();
    render(
      <BookableSpaceForm
        makerspaceId={7}
        initialValues={EMPTY_SPACE_FORM}
        onSubmit={submit}
        pending={false}
        submitLabel="Create"
      />,
      { wrapper: wrapper() },
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: /Booking price/ }), {
      target: { value: "14.50" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), {
      target: { value: "Studio" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ payment_amount: "14.50" }),
    );
  });

  it("renders a nested summary and runs generic reconciliation", async () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <PaymentReconcileActions
        makerspaceId={7}
        payment={{ id: 41, status: "pending", amount: "9.00", currency: "usd" }}
        invalidateKeys={[["bookings", 7]]}
      />,
      { wrapper: wrapper(client) },
    );

    expect(screen.getByText(/Payment.*9\.00/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Waive" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/41/waive",
      { method: "POST" },
    ));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["bookings", 7] });
  });

  it("edits membership dues through makerspace settings", async () => {
    const makerspace = {
      id: 7,
      name: "Community Lab",
      slug: "community-lab",
      public_code: "LAB7",
      telegram_group_chat_id: "",
      frontend_domain: null,
      hidden_from_central_directory: false,
      membership_dues_amount: "5.00",
    } as Makerspace;
    render(
      <MakerspaceMembershipSettings
        makerspace={makerspace}
        settings={makerspace}
        loading={false}
      />,
      { wrapper: wrapper() },
    );

    fireEvent.change(screen.getByRole("spinbutton", { name: "Dues amount" }), {
      target: { value: "25.00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save dues" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7",
      { method: "PATCH", body: JSON.stringify({ membership_dues_amount: "25.00" }) },
    ));
  });
});
