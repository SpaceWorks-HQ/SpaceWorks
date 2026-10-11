import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AppRoutes } from "./AppRoutes";
import { StructuredApiError } from "./lib/api";
import { expectNoA11yViolations } from "./test/axe";

const state = vi.hoisted(() => ({ mode: "central" as "single" | "central", request: vi.fn(), bootstrap: {
  makerspace: { slug: "lab", name: "Lab", logo_url: "/logo.png" },
  branding: { display_name: "Community Lab", welcome_body: "Make things together." }, theme: {}, modules: ["public_inventory", "request_workflow"], edition: "makerspace",
} }));
vi.mock("./lib/tenant", () => ({
  useTenant: () => ({ mode: state.mode, slug: "lab", modules: new Set(state.bootstrap.modules), bootstrap: state.bootstrap }),
  useTenantPath: () => (path = "") => state.mode === "single" ? `/${path}` : `/m/lab${path ? `/${path}` : ""}`,
}));
vi.mock("./lib/api", async () => ({ ...await vi.importActual<typeof import("./lib/api")>("./lib/api"), tenantPublicRequest: state.request }));
vi.mock("./features/inventory/usePublicInventory", () => ({ useTenantBootstrap: () => ({ data: state.bootstrap }) }));
vi.mock("./features/staff/StaffApp", () => ({ StaffApp: () => null }));
vi.mock("./features/staff/PlatformApps", () => ({ SuperadminPage: () => null }));
vi.mock("./features/members/MemberArea", async () => {
  const { useParams } = await import("react-router-dom");
  return { MemberArea: () => <h1>Member tab {useParams().memberTab ?? "overview"}</h1> };
});

function show(path: string) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><AppRoutes mode={state.mode} landing={<p>Directory</p>} /></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => { state.mode = "central"; state.bootstrap.edition = "makerspace"; state.request.mockReset(); });

it.each(["central", "single"] as const)("opens a public item directly in %s routing mode", async (mode) => {
  state.mode = mode;
  state.request.mockResolvedValue({ id: 7, name: "Public drill", description: "For woodworking", category_name: "Tools", availability: null, image_url: "/drill.jpg" });
  const base = mode === "single" ? "" : "/m/lab";
  const view = show(`${base}/items/7-old-name?utm_source=friend`);
  expect(await screen.findByRole("heading", { name: "Public drill" })).toBeVisible();
  expect(state.request).toHaveBeenCalledWith("lab", "/public/lab/inventory/7/");
  expect(document.title).toBe("Public drill · Community Lab");
  expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute("href", `${window.location.origin}${base}/items/7`);
  expect(screen.queryByText("Available")).toBeNull();
  expect(screen.getByRole("link", { name: "Request from the catalogue" })).toHaveAttribute("href", base || "/");
  await expectNoA11yViolations(view.container);
});

it("gives enumeration-safe missing/private UI and clears item metadata on navigation", async () => {
  state.request.mockRejectedValue(new StructuredApiError(404, { detail: "Item not found." }));
  const view = show("/m/lab/items/99");
  expect(await screen.findByRole("heading", { name: "Item not found" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  expect(document.title).toBe("Item not found · Community Lab");
  view.unmount();
  expect(document.head.querySelector('meta[property="og:title"]')).toBeNull();
});

it("refuses malformed identities without making an API request", async () => {
  show("/m/lab/items/not-an-id");
  expect(await screen.findByRole("heading", { name: "Item not found" })).toBeVisible();
  expect(state.request).not.toHaveBeenCalled();
});

it("shows the module-off response without retrying", async () => {
  state.request.mockRejectedValue(new StructuredApiError(400, { module: ["disabled"] }));
  show("/m/lab/items/7");
  expect(await screen.findByRole("heading", { name: "Inventory is not enabled" })).toBeVisible();
  await waitFor(() => expect(state.request).toHaveBeenCalledTimes(1));
});

it.each(["/member/events", "/m/lab/member/payments", "/m/lab/member/account"])("routes member deep link %s", async (path) => {
  show(path);
  expect(await screen.findByRole("heading", { name: `Member tab ${path.split("/").slice(-1)[0]}` })).toBeVisible();
});

it("routes a single-space member tab without a slug", async () => {
  state.mode = "single"; show("/member/bookings");
  expect(await screen.findByRole("heading", { name: "Member tab bookings" })).toBeVisible();
});

it.each(["events", "bookings"])("keeps the %s edition home canonical on the space's home URL", async (edition) => {
  state.bootstrap.edition = edition;
  state.request.mockResolvedValue([]);
  show("/m/lab");
  expect(await screen.findByRole("heading", { name: edition === "events" ? "Upcoming events" : "Book a makerspace" })).toBeVisible();
  expect(document.head.querySelector('link[rel="canonical"]')).toHaveAttribute("href", `${window.location.origin}/m/lab`);
});
