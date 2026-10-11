import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { DashboardPanel } from "./DashboardPanel";

vi.mock("../../../lib/api", () => ({ staffRequest: vi.fn().mockResolvedValue({
  scope_mode: "full", upcoming_events: 2, pending_bookings: 3, low_stock: 4, pending_payments: 5,
}) }));

it.each(["events", "machines", "membership", "bookings", "inventory"])("hides other-family tiles for %s-only makerspaces", async (family) => {
  const space = { id: 1, name: "Lab", slug: "lab", public_code: "LAB1", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false,
    enabled_modules: ["staff_admin", ...(family === "inventory" ? ["public_inventory", "request_workflow"] : [family])],
    enabled_features: family === "inventory" ? ["loans.enabled"] : [],
  };
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <DashboardPanel makerspace={space} canManageMakerspace />
  </MemoryRouter></QueryClientProvider>);
  if (family === "events") expect(await screen.findByRole("link", { name: "Upcoming events: 2. View list" })).toBeVisible();
  else expect(screen.queryByText("Upcoming events")).toBeNull();
  if (family === "bookings") expect(await screen.findByRole("link", { name: "Bookings awaiting approval: 3. View list" })).toBeVisible();
  else expect(screen.queryByText("Bookings awaiting approval")).toBeNull();
  if (family === "inventory") expect(await screen.findByRole("link", { name: "Out of stock: 4. View list" })).toBeVisible();
  else expect(screen.queryByText("Out of stock")).toBeNull();
  expect(screen.queryByText("Pending prints")).toBeNull();
  expect(screen.queryByText("Stocktakes awaiting approval")).toBeNull();
  expect(Boolean(screen.queryByText("Warranties expiring"))).toBe(["inventory", "machines"].includes(family));
});

it("shows the core debt queue to finance staff without settings authority or the rail module", async () => {
  const space = { id: 1, name: "Lab", slug: "lab", public_code: "LAB1", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: ["staff_admin"], enabled_features: [],
  };
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <DashboardPanel makerspace={space} canManageMakerspace={false} allowedTabs={["dashboard", "payments"]} />
  </MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "Pending payments: 5. View list" })).toBeVisible();
  expect(screen.queryByText("Failed emails")).toBeNull();
});
