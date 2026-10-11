import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { Inventory } from "./Inventory";
import type { Makerspace } from "./shared";

const { staffRequest, downloadStaffFile } = vi.hoisted(() => ({ staffRequest: vi.fn(), downloadStaffFile: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest, downloadStaffFile }));

it("exports the same active-and-archived zero-stock filter as the dashboard list", async () => {
  staffRequest.mockImplementation(async (path: string) => path.endsWith("/categories") ? [] : { count: 0, results: [] });
  downloadStaffFile.mockResolvedValue(undefined);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/admin/inventory?out_of_stock=true&archived=all"]}>
      <Inventory makerspace={{ id: 7, name: "Forge", slug: "forge" } as Makerspace} />
    </MemoryRouter>
  </QueryClientProvider>);
  await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(expect.stringContaining("archived=all&q=&out_of_stock=true")));
  fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
  await waitFor(() => expect(downloadStaffFile).toHaveBeenCalledWith("/admin/makerspace/7/inventory/export?format=csv&archived=all&q=&out_of_stock=true", "inventory-forge.csv"));
});
