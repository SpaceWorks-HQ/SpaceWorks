import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { bootstrapTenant, getAccessToken, memberRequest, refreshAccessToken, setAccessToken, StructuredApiError } from "../../lib/api";
import { MemberArea } from "./MemberArea";
vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(), bootstrapTenant: vi.fn(), getAccessToken: vi.fn(), memberRequest: vi.fn(), refreshAccessToken: vi.fn(), setAccessToken: vi.fn() }));
vi.mock("./MemberActivity", () => ({ MemberActivityPanel: () => null }));
vi.mock("./PartnerEvents", () => ({ PartnerEvents: () => null }));
vi.mock("./MemberProfilePanel", () => ({ MemberProfilePanel: () => <p>Profile controls</p> }));
vi.mock("./MemberCardPanel", () => ({ MemberCardPanel: () => null }));
vi.mock("./MemberDirectory", () => ({ MemberDirectory: () => null }));
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/m/workshop/member"]}><Routes><Route path="/m/:slug/member/*" element={<MemberArea />} /></Routes></MemoryRouter></QueryClientProvider>); }
function setup(modules = ["membership"], acceptanceRequired = false, status = "active") {
  vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 3, slug: "workshop", name: "Workshop", membership_policy: "request", geofence_enabled: false }, modules } as Awaited<ReturnType<typeof bootstrapTenant>>);
  vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(
    path === "/memberships/me" ? { memberships: [{ makerspace: { slug: "workshop", name: "Workshop" }, membership_status: status, role: "Member", waiver_acceptance_required: acceptanceRequired, can_verify: true, can_refer: false, referrals_enabled: false }], requests: [] }
      : path.endsWith("/waiver") ? { has_waiver: true, body: "Safety terms", version: "v1" }
      : path.endsWith("/current") ? { active: false }
      : path === "/memberships/invitations" ? { invitations: [] }
      : path === "/auth/me" ? { email_verified: true } : null,
  ) as ReturnType<typeof memberRequest>);
}
describe("MemberArea membership controls", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(getAccessToken).mockReturnValue(""); vi.mocked(refreshAccessToken).mockResolvedValue(false); });
  it("shows acceptance on file and active delegated-verifier controls", async () => {
    setup(); show(); expect(await screen.findByText("Current waiver acceptance is on file.")).toBeVisible();
    expect(screen.queryByText("Accept waiver")).toBeNull(); expect(screen.getByText("Member verification")).toBeVisible(); expect(screen.queryByText("Profile controls")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Account" }));
    expect(await screen.findByText("Profile controls")).toBeVisible();
  });
  it("offers acceptance when required but hides verifier and profiles module off", async () => {
    setup([], true); show(); expect(await screen.findByText("Accept waiver")).toBeVisible();
    expect(screen.queryByText("Member verification")).toBeNull(); expect(screen.queryByText("Profile controls")).toBeNull();
  });
  it("opens a bounded claim session without querying global account data", async () => {
    setup([]); vi.mocked(getAccessToken).mockReturnValue(`h.${btoa(JSON.stringify({ token_type: "claim_access" }))}.s`); show();
    expect(await screen.findByText("Temporary member session")).toBeVisible();
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/public/workshop/presence-sessions/current"));
    expect(memberRequest).not.toHaveBeenCalledWith("/memberships/me"); expect(memberRequest).not.toHaveBeenCalledWith("/member/archived-payments"); expect(memberRequest).not.toHaveBeenCalledWith("/auth/me");
  });
  it("redeems a code without refetching the global account routes under the new principal", async () => {
    setup([]);
    const signedOut = vi.mocked(memberRequest).getMockImplementation()!;
    vi.mocked(memberRequest).mockImplementation((path, options) => {
      if (path === "/memberships/me") return Promise.reject(new StructuredApiError(401, { detail: "Sign in" }));
      if (path === "/auth/claim/redeem") return Promise.resolve({ access: "claim-token" }) as ReturnType<typeof memberRequest>;
      return signedOut(path, options);
    });
    show(); fireEvent.change(await screen.findByLabelText("Claim code"), { target: { value: "MC1-code" } });
    const globalReads = () => vi.mocked(memberRequest).mock.calls.filter(([path]) => path === "/memberships/me" || path === "/member/archived-payments").length;
    const before = globalReads(); fireEvent.click(screen.getByText("Redeem claim code"));
    expect(await screen.findByText("Temporary member session")).toBeVisible();
    expect(setAccessToken).toHaveBeenCalledWith("claim-token"); expect(globalReads()).toBe(before);
  });
});
