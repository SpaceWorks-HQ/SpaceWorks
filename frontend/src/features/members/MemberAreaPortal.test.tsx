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
const modules = ["membership", "request_workflow", "bookings", "events"];
const activity = {
  active_hardware_loans: [{ label: "Drill loan", checked_out_at: "2026-10-01", due_at: "2026-10-12", overdue: false }],
  recent_presence_sessions: [], currently_checked_in: false, accountability: { waiver_acceptance_required: false },
  bookings: { upcoming: [{ space_name: "My bench", starts_at: "2026-11-01", ends_at: "2026-11-02", status: "confirmed" }], past: [] },
  event_registrations: [{ registration_id: 1, event_title: "My workshop", starts_at: "2026-11-01", status: "cancelled", checkin_token: null }],
  notices: [{ event: "loan", title: "Return your drill", body: "Due soon", level: "warning" }],
};
function setup(enabled = modules, hasMembership = true) {
  vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7, slug: "lab", name: "Lab", membership_policy: "invite_only" }, modules: enabled } as Awaited<ReturnType<typeof bootstrapTenant>>);
  vi.mocked(memberRequest).mockImplementation(async (path) => {
    if (path === "/memberships/me") return { memberships: hasMembership ? [{ makerspace: { slug: "lab", name: "Lab" }, membership_status: "active", role: "Member" }] : [], requests: [] };
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
function show(tab: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[`/m/lab/member/${tab}`]}><Routes><Route path="/m/:slug/member/*" element={<MemberArea />} /></Routes></MemoryRouter>
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
