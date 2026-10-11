import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { MemberArea } from "./MemberArea";
import { bootstrapTenant, memberRequest } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(),
  bootstrapTenant: vi.fn(), memberRequest: vi.fn(), refreshAccessToken: vi.fn().mockResolvedValue(false), getAccessToken: vi.fn().mockReturnValue(""),
}));
vi.mock("./MemberProfilePanel", () => ({ MemberProfilePanel: () => <h2>Profile controls</h2> }));
vi.mock("./MemberCardPanel", () => ({ MemberCardPanel: () => null }));
vi.mock("./MemberDirectory", () => ({ MemberDirectory: () => null }));
vi.mock("./PartnerEvents", () => ({ PartnerEvents: () => null }));
vi.mock("../bookings/MyBookings", () => ({ MyBookings: ({ slug }: { slug: string }) => <h2>Booking controls for {slug}</h2> }));
vi.mock("./MemberCertifications", () => ({ MemberCertifications: () => <h2>My certifications</h2> }));
vi.mock("../notifications/MemberNotifications", () => ({ MemberNotifications: ({ features }: { features: string[] }) => <>
  {features.includes("notifications.member_inbox") ? <h2>Personal inbox</h2> : null}
  {features.includes("notifications.member_preferences") ? <h2>Notification preferences</h2> : null}
</> }));
const modules = ["membership", "request_workflow", "bookings", "events"];
const activity = {
  active_hardware_loans: [{ label: "Drill loan", checked_out_at: "2026-10-01", due_at: "2026-10-12", overdue: false }],
  recent_presence_sessions: [], currently_checked_in: false, accountability: { waiver_acceptance_required: false },
  bookings: { upcoming: [{ space_name: "My bench", starts_at: "2026-11-01", ends_at: "2026-11-02", status: "confirmed" }], past: [] },
  event_registrations: [{ registration_id: 1, event_title: "My workshop", starts_at: "2026-11-01", status: "cancelled", checkin_token: null }],
  notices: [{ event: "loan", title: "Return your drill", body: "Due soon", level: "warning" }],
};
function setup(enabled = modules, hasMembership = true, features: string[] = [], status = "active") {
  vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules: enabled, features } as Awaited<ReturnType<typeof bootstrapTenant>>);
  vi.mocked(memberRequest).mockImplementation(async (path) => {
    if (path === "/memberships/me") return { memberships: hasMembership ? [{ makerspace: { slug: "lab", name: "Lab" }, membership_status: status, role: "Member", can_refer: true, referrals_enabled: true }] : [], requests: [] };
    if (path === "/memberships/invitations") return { invitations: [] };
    if (path.endsWith("/waiver")) return { has_waiver: false };
    if (path.endsWith("/current")) return { active: false };
    if (path.endsWith("/activity")) return activity;
    if (path === "/member/archived-payments") return [];
    if (path.endsWith("/payments")) return [{ id: 5, amount: "10.00", currency: "usd", status: "pending", subject_label: "Loan deposit", online_payment_available: false }];
    if (path === "/auth/me") return { email_verified: true };
    return {};
  });
}
function show(tab: string, base = "/m/lab/member") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[`${base}/${tab}`]}><Routes><Route path="/m/:slug/member/account" element={<h1>Self-service page</h1>} /><Route path="/member/account" element={<h1>Self-service page</h1>} /><Route path="/m/:slug/member/:memberTab" element={<MemberArea />} /><Route path="/member/:memberTab" element={<MemberArea />} /></Routes></MemoryRouter>
  </QueryClientProvider>) };
}
beforeEach(() => { vi.clearAllMocks(); });

it.each([["loans", "Drill loan"], ["bookings", "My bench"], ["events", "My workshop"]])("reuses only the selected %s activity section", async (tab, content) => {
  setup(); show(tab);
  expect(await screen.findByText(new RegExp(content))).toBeVisible();
  for (const other of ["Drill loan", "My bench", "My workshop"].filter((label) => label !== content)) expect(screen.queryByText(new RegExp(other))).toBeNull();
  expect(screen.queryByText("Profile controls")).toBeNull();
});

it("keeps borrower debts available with no membership or payment rail module", async () => {
  setup([], false); show("payments");
  expect(await screen.findByText("Loan deposit")).toBeVisible();
  expect(screen.getByText("Pay at the space")).toBeVisible();
  expect(screen.getByRole("button", { name: "Show documents" })).toBeVisible();
  expect(screen.queryByRole("tab", { name: "Loans" })).toBeNull();
  expect(memberRequest).not.toHaveBeenCalledWith("/member/makerspaces/7/activity");
});

it("shows personal derived notices in Inbox and moves profiles to Account", async () => {
  setup(); const view = show("inbox");
  expect(await screen.findByText("Return your drill")).toBeVisible();
  expect(screen.queryByText("Drill loan")).toBeNull();
  expect(vi.mocked(memberRequest).mock.calls.some(([path]) => path.includes("notifications"))).toBe(false);
  fireEvent.click(screen.getByRole("tab", { name: "Account" }));
  expect(await screen.findByText("Profile controls")).toBeVisible();
  expect(screen.queryByText("Return your drill")).toBeNull();
  await expectNoA11yViolations(view.container);
});

it("offers sign-in from an account-only Payments deep link", async () => {
  setup([], false);
  const { StructuredApiError } = await import("../../lib/api");
  const previous = vi.mocked(memberRequest).getMockImplementation()!;
  vi.mocked(memberRequest).mockImplementation((path, options) => path === "/memberships/me" ? Promise.reject(new StructuredApiError(401, { detail: "Sign in" })) : previous(path, options));
  show("payments");
  expect(await screen.findByRole("button", { name: "Sign in to your account" })).toBeVisible();
  await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/7/payments"));
});

it("hides cached member notices immediately when the membership module is turned off", async () => {
  setup(); const view = show("inbox");
  expect(await screen.findByText("Return your drill")).toBeVisible();
  act(() => view.client.setQueryData(["member", "lab", "bootstrap"], {
    makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules: [],
  }));
  await waitFor(() => expect(screen.queryByRole("tab", { name: "Inbox" })).toBeNull());
  expect(screen.queryByText("Return your drill")).toBeNull();
  expect(view.client.getQueryData(["member", "lab", "activity"])).toEqual(activity);
});

it("hides cached activity when refreshed membership authorization is refused", async () => {
  setup(); const view = show("inbox");
  expect(await screen.findByText("Return your drill")).toBeVisible();
  const { StructuredApiError } = await import("../../lib/api");
  const previous = vi.mocked(memberRequest).getMockImplementation()!;
  vi.mocked(memberRequest).mockImplementation((path, options) => path === "/memberships/me"
    ? Promise.reject(new StructuredApiError(401, { detail: "Sign in" })) : previous(path, options));
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["member", "memberships"] }); });
  await waitFor(() => expect(screen.queryByText("Return your drill")).toBeNull());
  expect(screen.getByRole("button", { name: "Sign in to your account" })).toBeVisible();
  expect(view.client.getQueryData(["member", "lab", "activity"])).toEqual(activity);
  fireEvent.click(screen.getByRole("tab", { name: "Payments" }));
  expect(screen.queryByText("Loan deposit")).toBeNull();
});

it.each(["membership.self_service", "membership.self_export"])("keeps %s and other account controls reachable through the Account tab", async (feature) => {
  setup([...modules, "machines", "member_accounts"], true, [feature]); show("overview");
  expect(await screen.findByRole("tab", { name: "Account" })).toHaveAttribute("href", "/m/lab/member/account-portal");
  expect(screen.queryByText("My certifications")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "Account" }));
  expect(await screen.findByText("My certifications")).toBeVisible();
  expect(await screen.findByRole("heading", { name: "Refer someone" })).toBeVisible();
  const link = screen.getByRole("link", { name: "Manage your account" });
  expect(link).toHaveAttribute("href", "/m/lab/member/account");
  fireEvent.click(link);
  expect(await screen.findByRole("heading", { name: "Self-service page" })).toBeVisible();
});

it("uses the unscoped self-service URL on a single-space portal", async () => {
  setup(["membership", "member_accounts"], true, ["membership.self_service"]); show("account-portal", "/member");
  expect(await screen.findByRole("link", { name: "Manage your account" })).toHaveAttribute("href", "/member/account");
});

it.each([
  [[], ["membership.self_service"], "active"],
  [["membership"], ["membership.self_export"], "active"],
  [["membership", "member_accounts"], [], "active"],
  [["membership", "member_accounts"], ["membership.self_service"], "revoked"],
] as const)("hides self-service when its module, feature or membership gate closes (%j)", async (enabled, features, status) => {
  setup([...enabled], true, [...features], status); show("account-portal");
  await screen.findByRole("link", { name: "Manage two-step sign-in" });
  expect(screen.queryByRole("link", { name: "Manage your account" })).toBeNull();
});

it("hides cached account controls when their modules turn off", async () => {
  setup([...modules, "machines", "member_accounts"], true, ["membership.self_service"]);
  const view = show("account-portal");
  expect(await screen.findByText("My certifications")).toBeVisible();
  expect(await screen.findByRole("heading", { name: "Refer someone" })).toBeVisible();
  act(() => view.client.setQueryData(["member", "lab", "bootstrap"], {
    makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules: [], features: ["membership.self_service"],
  }));
  await waitFor(() => expect(screen.queryByText("My certifications")).toBeNull());
  expect(screen.queryByText("Profile controls")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Refer someone" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Manage your account" })).toBeNull();
});

it("places the personal inbox and preferences only in Inbox and respects the notifications module", async () => {
  setup([...modules, "notifications"], true, ["notifications.member_inbox", "notifications.member_preferences"]);
  const view = show("overview");
  expect(await screen.findByText("Return your drill")).toBeVisible();
  expect(screen.queryByText("Personal inbox")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "Inbox" }));
  expect(await screen.findByText("Personal inbox")).toBeVisible();
  expect(screen.getByText("Notification preferences")).toBeVisible();
  act(() => view.client.setQueryData(["member", "lab", "bootstrap"], {
    makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules, features: ["notifications.member_inbox", "notifications.member_preferences"],
  }));
  await waitFor(() => expect(screen.queryByText("Personal inbox")).toBeNull());
  expect(screen.queryByText("Notification preferences")).toBeNull();
  expect(screen.getByText("Return your drill")).toBeVisible();
});

it("places booking management only in Bookings and removes it when bookings turn off", async () => {
  setup(); const view = show("overview");
  expect(await screen.findByText("Return your drill")).toBeVisible();
  expect(screen.queryByText("Booking controls for lab")).toBeNull();
  fireEvent.click(screen.getByRole("tab", { name: "Bookings" }));
  expect(await screen.findByText("Booking controls for lab")).toBeVisible();
  act(() => view.client.setQueryData(["member", "lab", "bootstrap"], {
    makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules: ["membership"], features: [],
  }));
  await waitFor(() => expect(screen.queryByText("Booking controls for lab")).toBeNull());
  expect(screen.queryByText(/My bench/)).toBeNull();
});
