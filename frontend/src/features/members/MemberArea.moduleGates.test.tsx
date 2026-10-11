import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { bootstrapTenant, memberRequest } from "../../lib/api";
import { MemberArea } from "./MemberArea";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(),
  bootstrapTenant: vi.fn(), memberRequest: vi.fn(), refreshAccessToken: vi.fn().mockResolvedValue(false), getAccessToken: vi.fn().mockReturnValue(""),
}));
vi.mock("./PartnerEvents", () => ({ PartnerEvents: () => <h2>Partner events</h2> }));
vi.mock("./MemberActivity", () => ({ MemberActivityPanel: () => null }));
vi.mock("./MemberCardPanel", () => ({ MemberCardPanel: () => null }));
vi.mock("./MemberDirectory", () => ({ MemberDirectory: () => null }));
vi.mock("./MemberProfilePanel", () => ({ MemberProfilePanel: () => null }));
vi.mock("../bookings/MyBookings", () => ({ MyBookings: () => <h2>My booking history</h2> }));

function setup(modules: string[], member = true, status = "active") {
  vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7, slug: "lab", name: "Lab", public_code: "LAB1", location: "", membership_policy: "request", geofence_enabled: false }, modules, features: [], workflows: [], frontend: { type: "makerspace", hostname: "", allowed_origins: [] }, theme: {}, branding: {}, email_enabled: false, public_api: { base_url: "", publishable_key: "", inventory_path: "" } } as Awaited<ReturnType<typeof bootstrapTenant>>);
  vi.mocked(memberRequest).mockImplementation(async (path) => {
    if (path === "/memberships/me") return { memberships: member ? [{ makerspace: { slug: "lab", name: "Lab" }, membership_status: status, role: "Member" }] : [], requests: [] };
    if (path === "/memberships/invitations") return { invitations: [] };
    if (path === "/member/archived-payments" || path.endsWith("/payments")) return [];
    if (path.endsWith("/waiver")) return { has_waiver: false };
    if (path.endsWith("/current")) return { active: false };
    if (path.endsWith("/activity")) return {};
    if (path === "/auth/me") return { email_verified: true };
    return {};
  });
}
function show(tab = "overview") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[`/m/lab/member/${tab}`]}><Routes><Route path="/m/:slug/member/:memberTab" element={<MemberArea />} /></Routes></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => vi.clearAllMocks());

it.each(["events", "machines", "membership", "bookings", "inventory"])("keeps disabled presence and partner events hidden in a %s-only setup", async (family) => {
  setup(family === "inventory" ? ["request_workflow"] : [family]); show();
  // Wait for the real member branch, so absence assertions cannot pass while
  // session restoration still hides every panel.
  expect(await screen.findByRole("heading", { name: "Membership" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Presence" })).toBeNull();
  expect(screen.queryByText("Partner events")).toBeNull();
  expect(vi.mocked(memberRequest).mock.calls.some(([path]) => path.includes("presence-sessions"))).toBe(false);
});

it("a stale events deep link never mounts PartnerEvents with events off", async () => {
  setup(["membership"]); show("events");
  expect(await screen.findByRole("heading", { name: "Membership" })).toBeVisible();
  expect(screen.queryByText("Partner events")).toBeNull();
});

it("mounts partner events when both the module and active member identity are present", async () => {
  setup(["membership", "events"]); show("events");
  expect(await screen.findByText("Partner events")).toBeVisible();
});

it("bookings-only accounts can reach their own booking history", async () => {
  setup(["bookings"], false); show("bookings");
  expect(await screen.findByText("My booking history")).toBeVisible();
  expect(screen.queryByText("An active membership is required to view your activity.")).toBeNull();
  expect(vi.mocked(memberRequest).mock.calls.some(([path]) => path.endsWith("/activity"))).toBe(false);
});

it("renders presence only with the module and active membership", async () => {
  setup(["membership", "presence"]); show();
  expect(await screen.findByRole("heading", { name: "Presence" })).toBeVisible();
  await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/public/lab/presence-sessions/current"));
});
