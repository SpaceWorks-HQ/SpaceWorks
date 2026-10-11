import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { PublicMachinesPage } from "./PublicMachinesPage";
import { tenantPublicRequest } from "../../lib/api";

vi.mock("../../lib/api", () => ({ tenantPublicRequest: vi.fn(), StructuredApiError: class extends Error {} }));
vi.mock("../../lib/tenant", () => ({
  useTenant: () => ({ mode: "single", slug: "lab", bootstrap: {
    features: ["machines.public_detail"], makerspace: { name: "Lab" }, branding: {},
  } }),
  useTenantPath: () => () => "/m/lab",
}));
vi.mock("../../lib/useTenantBranding", () => ({ useTenantBranding: () => ({}) }));
vi.mock("./usePublicInventory", () => ({ useTenantBootstrap: () => ({}) }));

it("loads subsequent machine pages through the tenant transport", async () => {
  const request = vi.mocked(tenantPublicRequest);
  request.mockImplementation(async (_slug, path) => ({
    count: 25, next: path.includes("page=1") ? "https://untrusted.example/page2" : null, previous: null,
    results: [{ id: 1, name: path.includes("page=2") ? "Second page laser" : "First page laser",
      machine_type: { id: 4, name: "Laser", icon: "" }, status: "idle", image_url: null, usage_hours: "0.00",
      queue: { length: 2, eta_minutes: null } }],
  }));
  render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <PublicMachinesPage />
  </QueryClientProvider></MemoryRouter>);
  await screen.findByText("First page laser");
  expect(screen.getByText("2 queued jobs · Estimate unavailable")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("Second page laser");
  await waitFor(() => expect(request).toHaveBeenCalledWith("lab", "/public/lab/machines/details?page=2&page_size=24"));
  expect(request.mock.calls.every(call => call[1].startsWith("/public/lab/"))).toBe(true);
});
