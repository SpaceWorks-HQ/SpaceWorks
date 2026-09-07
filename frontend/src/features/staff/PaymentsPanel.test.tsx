import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { PaymentsPanel } from "./PaymentsPanel";
import type { PaymentRow } from "./paymentsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const payment: PaymentRow = {
  id: 41,
  subject_type: "booking",
  subject_id: 9,
  subject_label: "Laser cutter booking",
  status: "pending",
  amount: "125.00",
  currency: "usd",
  refunded_amount: "0.00",
  refunds: [],
  created_at: "2026-07-20T10:00:00Z",
  updated_at: "2026-07-20T10:00:00Z",
};

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) =>
    options?.method === "POST" ? payment : [payment]);
});

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <PaymentsPanel makerspaceId={7} />
      </QueryClientProvider>,
    ),
  };
}

async function waitForPayment() {
  await screen.findByText("Laser cutter booking");
}

describe("PaymentsPanel", () => {
  it("renders all four subject filter choices", async () => {
    renderPanel();
    await waitForPayment();

    const subjectFilter = screen.getByRole("combobox", { name: "Subject" });
    expect(subjectFilter).toHaveTextContent("Machine service");
    expect(subjectFilter).toHaveTextContent("Booking");
    expect(subjectFilter).toHaveTextContent("Event registration");
    expect(subjectFilter).toHaveTextContent("Membership dues");
  });

  it("runs a single action and invalidates every payment view after success", async () => {
    const { queryClient } = renderPanel();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    await waitForPayment();

    // Marking paid offline is two steps now: the API requires a receipt saying how and
    // when the money arrived, so the button opens the form and the request only goes
    // once staff confirm it.
    fireEvent.click(screen.getByRole("button", { name: "Mark offline" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm payment" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/41/mark-offline",
      expect.objectContaining({ method: "POST" }),
    ));
    // Pick the settlement call itself: a list refetch follows it with no body.
    const call = staffRequest.mock.calls.find(
      ([path]) => path === "/admin/makerspace/7/payments/41/mark-offline",
    )!;
    const settlement = JSON.parse((call[1] as { body: string }).body).settlement;
    expect(settlement.method).toBe("cash");
    expect(settlement.received_at).toEqual(expect.any(String));
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["payments", 7] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["operations-report", "payment-reconciliation"] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard", 7] });
    });
  });

  it("runs a bulk action with the selected payment ids", async () => {
    renderPanel();
    await waitForPayment();

    fireEvent.click(screen.getByRole("checkbox", { name: "Select row 41" }));
    expect(screen.getByText("1 selected")).toBeVisible();
    fireEvent.click(screen.getAllByRole("button", { name: "Waive" })[0]);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/bulk/waive",
      { method: "POST", body: JSON.stringify({ ids: [41] }) },
    ));
  });

  it("keeps the visible list, reports a 409 conflict, and refetches", async () => {
    let listRequests = 0;
    let finishRefetch: ((rows: PaymentRow[]) => void) | undefined;
    staffRequest.mockImplementation((_path: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        return Promise.reject(new StructuredApiError(409, { detail: "Payment status changed" }));
      }
      listRequests += 1;
      if (listRequests === 1) return Promise.resolve([payment]);
      return new Promise<PaymentRow[]>((resolve) => { finishRefetch = resolve; });
    });
    renderPanel();
    await waitForPayment();

    fireEvent.click(screen.getByRole("button", { name: "Waive" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Payment status changed");
    await waitFor(() => expect(listRequests).toBe(2));
    expect(screen.getByText("Laser cutter booking")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payments/41/waive",
      { method: "POST" },
    );

    finishRefetch?.([payment]);
  });
});
