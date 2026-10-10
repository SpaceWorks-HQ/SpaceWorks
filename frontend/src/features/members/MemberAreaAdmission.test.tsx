import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { bootstrapTenant, memberRequest, tenantPublicRequest } from "../../lib/api";
import { MemberArea } from "./MemberArea";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(), bootstrapTenant: vi.fn(), memberRequest: vi.fn(), tenantPublicRequest: vi.fn(), refreshAccessToken: vi.fn().mockResolvedValue(false), getAccessToken: vi.fn().mockReturnValue("") }));
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/m/workshop/member"]}><Routes><Route path="/m/:slug/member" element={<MemberArea />} /></Routes></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7, slug: "workshop", name: "Workshop", membership_policy: "request" }, modules: ["membership"] } as Awaited<ReturnType<typeof bootstrapTenant>>);
  vi.mocked(tenantPublicRequest).mockResolvedValue({ join_mode: "approval", vouches_required: 1, payment_timing: "before_activation", application_schema: null, joining_fee: "0.00", default_plan: null });
});
describe("applicant member dashboard", () => {
  it("clears private application answers when navigating to another makerspace", async () => {
    vi.mocked(bootstrapTenant).mockImplementation(({ slug } = {}) => Promise.resolve({ makerspace: { id: slug === "second" ? 8 : 7, slug: slug ?? "workshop", name: slug ?? "Workshop", membership_policy: "request" }, modules: ["membership"] }) as ReturnType<typeof bootstrapTenant>);
    vi.mocked(tenantPublicRequest).mockResolvedValue({ join_mode: "approval", vouches_required: 1, payment_timing: "after_activation", joining_fee: "0.00", default_plan: null, application_schema: [{ id: "why", label: "Why join?", type: "short_text", required: true, options: [] }] });
    vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(path === "/memberships/me" ? { memberships: [], requests: [] } : path === "/memberships/invitations" ? { invitations: [] } : path === "/auth/me" ? { email_verified: true } : []) as ReturnType<typeof memberRequest>);
    function SwitchSpace() {
      const navigate = useNavigate();
      return <><button onClick={() => navigate("/m/second/member")}>Switch space</button><MemberArea /></>;
    }
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/m/workshop/member"]}><Routes><Route path="/m/:slug/member" element={<SwitchSpace />} /></Routes></MemoryRouter></QueryClientProvider>);
    fireEvent.change(await screen.findByLabelText(/Why join/), { target: { value: "Private first-space answer" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch space" }));
    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledWith("second", "/public/second/membership-admission"));
    expect(await screen.findByLabelText(/Why join/)).toHaveValue("");
  });
  it("shows awaiting-payment and the offline debt to an applicant who is not yet a member", async () => {
    const admission = { id: 21, state: "awaiting_payment", admission_payment: { id: 8, status: "pending", amount: "25.00", currency: "usd" } };
    vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(
      path === "/memberships/me" ? { memberships: [], requests: [{ ...admission, kind: "join", makerspace: { id: 7, slug: "workshop", name: "Workshop" } }] }
        : path.endsWith("/admission") ? admission
        : path.endsWith("/payments") ? [{ id: 8, status: "pending", amount: "25.00", currency: "usd", subject_label: "Admission", online_payment_available: false }]
        : path === "/memberships/invitations" ? { invitations: [] }
        : path === "/auth/me" ? { email_verified: true } : [],
    ) as ReturnType<typeof memberRequest>);
    show();
    expect(await screen.findByText("Membership awaiting payment")).toBeVisible();
    expect(await screen.findByText("Pay at the space")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Request to join" })).toBeNull();
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/7/admission"));
    expect(memberRequest).not.toHaveBeenCalledWith("/member/makerspaces/7/activity");
  });
  it("does not call admission endpoints when the membership module is off", async () => {
    vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7, slug: "workshop", name: "Workshop", membership_policy: "request" }, modules: [] } as unknown as Awaited<ReturnType<typeof bootstrapTenant>>);
    vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(path === "/memberships/me" ? { memberships: [], requests: [] } : path === "/memberships/invitations" ? { invitations: [] } : path === "/auth/me" ? { email_verified: true } : []) as ReturnType<typeof memberRequest>);
    show();
    expect(await screen.findByRole("button", { name: "Request to join" })).toBeVisible();
    expect(tenantPublicRequest).not.toHaveBeenCalled();
    expect(memberRequest).not.toHaveBeenCalledWith("/member/makerspaces/7/admission");
  });
  it("allows a revoked member to reapply without offering vouching authority", async () => {
    vi.mocked(tenantPublicRequest).mockResolvedValue({ join_mode: "vouch", vouches_required: 1, payment_timing: "after_activation", application_schema: null, joining_fee: "0.00", default_plan: null });
    vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(path === "/memberships/me" ? { memberships: [{ makerspace: { slug: "workshop", name: "Workshop" }, membership_status: "revoked", role: "Member" }], requests: [] } : path === "/memberships/invitations" ? { invitations: [] } : path === "/auth/me" ? { email_verified: true } : []) as ReturnType<typeof memberRequest>);
    show();
    expect(await screen.findByRole("button", { name: "Request to join" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Record my vouch" })).toBeNull();
  });
});
