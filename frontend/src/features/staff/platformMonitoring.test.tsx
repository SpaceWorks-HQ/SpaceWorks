import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformDashboardPanel } from "./PlatformDashboardPanel";
import { TenantUsagePanel } from "./TenantUsagePanel";
import { getStaffAccess } from "./staffAccess";
import { staffTabPath } from "./staffTabs";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

const space = { id: 7, name: "Forge", slug: "forge" } as Makerspace;
const usage = { makerspace_id: 7, managed: true, resources: [
  { key: "products", label: "products", used: 412, limit: 500, unit: "count" },
  { key: "storage", label: "storage", used: 1024 ** 2, limit: 2 * 1024 ** 2, unit: "bytes" },
] };
const dashboard = {
  checked_at: "2026-10-11T00:00:00Z", tenants_by_state: { active: 1, importing: 0, archived: 0 },
  usage_totals: { products: 412, storage: 1024 ** 2 }, tenants: [{ id: 7, name: "Forge", slug: "forge", usage }],
  backup: { status: "complete", automatic_enabled: true, last_success_at: null }, offsite: [],
  scheduler: [{ name: "return-reminders", cadence_minutes: 60, last_run_at: null, status: "warn" }],
  updates: { status: "queued", current_version: "v1", available_version: "v2", pending: true },
  failed_deliveries: { email: 2, notifications: 3 },
};
const problems = { checked_at: dashboard.checked_at, status: "warn", results: [
  { key: "storage", status: "warn", message: "Forge: storage is at least 90% of its allowance.", fix_url: "/m/forge/admin/usage", makerspace_id: 7 },
] };

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <MemoryRouter><QueryClientProvider client={client}>{children}</QueryClientProvider></MemoryRouter>;
}

describe("platform monitoring", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((path: string) => Promise.resolve(
      path.endsWith("/problems") ? problems : path.endsWith("/dashboard") ? dashboard : usage,
    ));
  });

  it("limits platform navigation to central superadmins and usage to managers", () => {
    expect(getStaffAccess(["manage_makerspace"], false, false).allowedTabs).toContain("usage");
    expect(getStaffAccess(["view_inventory"], false, false).allowedTabs).not.toContain("usage");
    expect(getStaffAccess(["manage_makerspace"], false, false).allowedTabs).not.toContain("platform-dashboard");
    expect(getStaffAccess([], true, false).allowedTabs).toContain("platform-dashboard");
    expect(getStaffAccess([], true, true).allowedTabs).not.toContain("platform-dashboard");
    expect(staffTabPath("platform-dashboard", false, "forge")).toBe("/admin/platform-dashboard");
  });

  it("renders operational signals, scheduler and actionable check links", async () => {
    render(<PlatformDashboardPanel />, { wrapper });
    expect(await screen.findByText("Failed emails: 2")).toBeInTheDocument();
    expect(screen.getByText("return-reminders")).toBeInTheDocument();
    expect(screen.getByText(/Pending update/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Inspect" })).toHaveAttribute("href", "/m/forge/admin/usage");
    expect(staffRequest).toHaveBeenCalledWith("/admin/platform/dashboard");
    expect(staffRequest).toHaveBeenCalledWith("/admin/platform/problems");
    fireEvent.click(screen.getByRole("button", { name: "Refresh dashboard and checks" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(4));
  });

  it("renders counts and byte limits using the selected makerspace route", async () => {
    render(<TenantUsagePanel makerspace={space} />, { wrapper });
    expect(await screen.findByText("412")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("1 MiB")).toBeInTheDocument();
    expect(screen.getByText("82.4%")).toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/usage");
  });

  it("refetches usage for a new tenant rather than reusing another tenant's counts", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = (makerspace: Makerspace) => <MemoryRouter><QueryClientProvider client={client}><TenantUsagePanel makerspace={makerspace} /></QueryClientProvider></MemoryRouter>;
    const rendered = render(view(space));
    await screen.findByText("412");
    staffRequest.mockResolvedValue({ ...usage, makerspace_id: 8, resources: [{ ...usage.resources[0], used: 12 }] });
    rendered.rerender(view({ ...space, id: 8, name: "Second" }));
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.queryByText("412")).not.toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/8/usage");
  });

  it("shows API failure with a refresh control", async () => {
    staffRequest.mockRejectedValue(new Error("Usage could not be loaded"));
    render(<TenantUsagePanel makerspace={space} />, { wrapper });
    expect(await screen.findByRole("alert")).toHaveTextContent("Usage could not be loaded");
    expect(screen.getByRole("button", { name: "Refresh usage" })).toBeEnabled();
  });
});
