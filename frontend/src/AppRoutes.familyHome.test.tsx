import { render, screen } from "@testing-library/react";
import { MemoryRouter, useParams } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { TenantBootstrap } from "./lib/api";
import { AppRoutes } from "./AppRoutes";

const { tenant, query } = vi.hoisted(() => ({ tenant: vi.fn(), query: vi.fn() }));
vi.mock("./lib/tenant", () => ({ useTenant: tenant }));
vi.mock("./features/inventory/usePublicInventory", () => ({ useTenantBootstrap: query }));
vi.mock("./features/inventory/PublicInventoryPage", () => ({ PublicInventoryPage: () => <h1>Inventory home</h1> }));
vi.mock("./features/inventory/PublicEventsPage", () => ({ PublicEventsPage: () => <h1>Events home</h1> }));
vi.mock("./features/bookings/PublicBookingsPage", () => ({ PublicBookingsPage: () => <h1>Bookings home</h1> }));
vi.mock("./features/inventory/PublicMachinesPage", () => ({ PublicMachinesPage: () => <h1>Machines home</h1> }));
vi.mock("./features/members/MemberArea", () => ({ MemberArea: () => <h1>Membership home</h1> }));
vi.mock("./features/inventory/PublicEventDetailPage", () => ({ PublicEventDetailPage: () => <h1>Event {useParams().publicToken}</h1> }));
vi.mock("./features/staff/StaffApp", () => ({ StaffApp: () => null }));
vi.mock("./features/staff/PlatformApps", () => ({ SuperadminPage: () => null }));
vi.mock("./features/kiosk/PublicDeskKioskPage", () => ({ PublicDeskKioskPage: () => null }));
vi.mock("./features/kiosk/ScannerPage", () => ({ ScannerPage: () => null }));

const core = ["public_inventory", "request_workflow", "staff_admin", "qr_management", "evidence_uploads", "scanner"];
function bootstrap(family: string): TenantBootstrap {
  return {
    makerspace: { id: 1, name: "Lab", slug: "lab", public_code: "LAB1", location: "", geofence_enabled: false,
      membership_policy: "request", public_site_enabled: true, public_inventory_enabled: true },
    modules: [...core, ...(family === "inventory" ? [] : [family])],
    features: family === "inventory" ? ["loans.enabled"] : [], workflows: [], edition: "makerspace",
    frontend: { type: "makerspace", hostname: "", allowed_origins: [] }, theme: {}, branding: {}, email_enabled: false,
    public_api: { base_url: "/api/v1", publishable_key: "pk_test", inventory_path: "" },
  };
}
function show(data: TenantBootstrap, mode: "single" | "central" = "central", path?: string) {
  tenant.mockReturnValue({ mode, bootstrap: mode === "single" ? data : null });
  query.mockReturnValue({ data });
  return render(<MemoryRouter initialEntries={[path ?? (mode === "single" ? "/" : "/m/lab")]}>
    <AppRoutes mode={mode} landing={<h1>Directory</h1>} />
  </MemoryRouter>);
}
beforeEach(() => vi.clearAllMocks());

it.each(["events", "machines", "membership", "bookings", "inventory"])("routes an %s-only tenant to its family on a shared deployment", async (family) => {
  show(bootstrap(family));
  expect(await screen.findByRole("heading", { name: `${family[0].toUpperCase()}${family.slice(1)} home` })).toBeVisible();
  if (family !== "inventory") expect(screen.queryByText("Inventory home")).toBeNull();
});

it("uses capabilities over the edition and respects an available landing preference", async () => {
  const data = bootstrap("events"); data.modules.push("bookings"); data.edition = "events";
  data.makerspace.public_landing_page = "bookings";
  show(data, "single");
  expect(await screen.findByText("Bookings home")).toBeVisible();
});

it("falls back when the saved landing family is disabled", async () => {
  const data = bootstrap("machines"); data.makerspace.public_landing_page = "inventory";
  show(data);
  expect(await screen.findByText("Machines home")).toBeVisible();
});

it("hides the catalogue when its publication flag is off", async () => {
  const data = bootstrap("inventory"); data.modules.push("events"); data.makerspace.public_inventory_enabled = false;
  show(data);
  expect(await screen.findByText("Events home")).toBeVisible();
});

it("renders no family when the public site is off", () => {
  const data = bootstrap("events"); data.makerspace.public_site_enabled = false;
  show(data);
  expect(screen.getByText("No public programme is available.")).toBeVisible();
});

it.each(["single", "central"] as const)("registers the lazy event detail in %s routing", async (mode) => {
  show(bootstrap("events"), mode, mode === "single" ? "/events/abc123" : "/m/lab/events/abc123");
  expect(await screen.findByRole("heading", { name: "Event abc123" })).toBeVisible();
});

it("waits for bootstrap before selecting a family", () => {
  tenant.mockReturnValue({ mode: "central", bootstrap: null }); query.mockReturnValue({ data: undefined });
  render(<MemoryRouter initialEntries={["/m/lab"]}><AppRoutes mode="central" landing={null} /></MemoryRouter>);
  expect(screen.getByText("Loading...")).toBeVisible();
  expect(screen.queryByText("Inventory home")).toBeNull();
});
