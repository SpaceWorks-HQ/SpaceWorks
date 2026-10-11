import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../../lib/api";
import { ReorderSuggestions } from "./ReorderSuggestions";

vi.mock("../../../lib/api", () => ({ staffRequest: vi.fn() }));

describe("reorder suggestions", () => {
  it("creates a draft for the selected product in the selected makerspace", async () => {
    const request = vi.mocked(staffRequest);
    request.mockImplementation(async (path) => path.endsWith("reorder-draft") ? { id: 81 } :
      { count: 1, results: [{ id: 7, name: "Driver", available_quantity: 2, reorder_point: 3, reorder_quantity: 6, supplier: "Tools Ltd", sku: "D1" }] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(<QueryClientProvider client={client}><ReorderSuggestions makerspaceId={5} canProcure /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Draft order for 6" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspace/5/inventory/reorder-draft",
      { method: "POST", body: JSON.stringify({ product_id: 7 }) }));
    expect(await screen.findByText(/Procurement draft #81/)).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["procurement", 5] });
  });
});
