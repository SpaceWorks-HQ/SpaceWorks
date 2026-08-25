import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrinterPool } from "../../../../generated/api";
import { ConsumablePoolList } from "./SharedConsumablesSection";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

function pool(id: number, material: string, remaining: string, threshold: string | null, isPublic = true): PrinterPool {
  return {
    id,
    machine_id: null,
    machine_type_id: null,
    material,
    color: "Signal red",
    brand: "Maker",
    unit: "grams",
    initial_grams: "100",
    remaining_grams: remaining,
    low_threshold_grams: threshold,
    is_active: true,
    is_public: isPublic,
    created_at: "",
    updated_at: "",
  };
}

function renderList(pools: PrinterPool[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsumablePoolList makerspaceId={1} pools={pools} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({});
});

describe("ConsumablePoolList", () => {
  it("shows danger, warning and success stock bands with proportions and labelled colours", () => {
    renderList([
      pool(1, "Empty PLA", "0", "10"),
      pool(2, "Low PETG", "10", "10"),
      pool(3, "Healthy ABS", "75", "10"),
    ]);

    expect(screen.getByText("Empty").parentElement).toHaveClass("bg-danger");
    expect(screen.getByText("Low stock").parentElement).toHaveClass("bg-warn");
    expect(screen.getByText("In stock").parentElement).toHaveClass("bg-success");
    expect(screen.getByRole("progressbar", { name: "Maker Healthy ABS Signal red remaining" })).toHaveAttribute("aria-valuenow", "75");
    expect(screen.getAllByText("Colour: Signal red")).toHaveLength(3);
    expect(screen.getByText("75", { selector: "strong" }).parentElement).toHaveTextContent("75 / 100 grams");
  });

  it("patches requester visibility and adjusts stock through an inline form", async () => {
    renderList([pool(4, "Private PLA", "50", "10", false)]);

    expect(screen.getByText("Hidden from requesters")).toBeVisible();
    // The accessible name leads with the visible text ("Hidden") so voice control can act on what
    // the user reads -- WCAG 2.5.3 Label in Name. Asserting on it here is what keeps that true.
    fireEvent.click(screen.getByRole("button", { name: "Hidden: Maker Private PLA Signal red — activate to show to requesters" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/machine-service/consumable-pools/4",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ is_public: true }) }),
    ));

    fireEvent.click(screen.getByRole("button", { name: "Adjust stock" }));
    fireEvent.change(screen.getByLabelText("Adjustment (grams, + or −)"), { target: { value: "-12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save adjustment" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/machine-service/consumable-pools/4/adjustments",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ quantity_delta: "-12.5", reason: "Manual correction" }) }),
    ));
  });
});
