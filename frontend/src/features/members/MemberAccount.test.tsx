import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest, bootstrapTenant, refreshAccessToken } from "../../lib/api";
import { MemberAccountPage } from "./MemberAccountPage";
import { MemberAccountProfile } from "./MemberAccountProfile";
import { MemberAccountSessions } from "./MemberAccountSessions";
import { MemberAccountMembership } from "./MemberAccountMembership";
import { MemberAccountExports } from "./MemberAccountExports";

vi.mock("../../lib/api", async () => ({ ...await vi.importActual("../../lib/api"), memberRequest: vi.fn(), bootstrapTenant: vi.fn(), refreshAccessToken: vi.fn(), clearAccessToken: vi.fn() }));
vi.mock("./MemberClaimSession", () => ({ hasClaimSession: () => false }));
vi.mock("./MemberAuthPanel", () => ({ MemberAuthPanel: ({ onAuthenticated }: { onAuthenticated: () => void }) => <button onClick={onAuthenticated}>Complete sign in</button> }));

function show(node: React.ReactNode, entry = "/", client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })) {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}>{node}</MemoryRouter></QueryClientProvider>);
}
const prefix = "/member/makerspaces/7/account";
const profile = { display_name: "Ada", first_name: "Ada", last_name: "L", phone: "123" };
const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

beforeEach(() => { vi.resetAllMocks(); vi.mocked(refreshAccessToken).mockResolvedValue(true); });

describe("Member account", () => {
  it("edits member profile fields and refreshes the query", async () => {
    vi.mocked(memberRequest).mockResolvedValue(profile);
    show(<MemberAccountProfile makerspaceId={7} />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Display name" }), { target: { value: "Ada Maker" } });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith(`${prefix}/profile`, { method: "PATCH", body: JSON.stringify({ ...profile, display_name: "Ada Maker" }) }));
    expect(await screen.findByText("Profile saved.")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Email" })).toBeNull();
  });

  it("revokes the selected current session and reports sign-out", async () => {
    const signedOut = vi.fn();
    vi.mocked(memberRequest).mockResolvedValue(page([{ id: "web:abc", kind: "web", created_at: "2026-10-01T00:00:00Z", expires_at: null, last_used_at: null, current: true }]));
    show(<MemberAccountSessions makerspaceId={7} onSignedOut={signedOut} />);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke this session" }));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith(`${prefix}/sessions/web%3Aabc`, { method: "DELETE" }));
    await waitFor(() => expect(signedOut).toHaveBeenCalled());
  });

  it("requires a reason and confirmation before leaving", async () => {
    const left = vi.fn();
    vi.mocked(memberRequest).mockResolvedValue({ status: "active", renewal_cancelled_at: null });
    show(<MemberAccountMembership makerspaceId={7} onLeft={left} />);
    fireEvent.click(await screen.findByRole("button", { name: "Leave makerspace" }));
    expect(screen.getByRole("button", { name: "Confirm leave" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Reason" }), { target: { value: "Moving" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm leave" }));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith(`${prefix}/leave`, { method: "POST", body: JSON.stringify({ reason: "Moving" }) }));
    await waitFor(() => expect(left).toHaveBeenCalled());
  });

  it("requests an export and shows a short-lived download link", async () => {
    vi.mocked(memberRequest).mockImplementation(async (path, options) => {
      if (path.endsWith("/download")) return { url: "https://files.example.test/signed", expires_at: "2030-01-01T00:05:00Z" };
      if (options?.method === "POST") return { id: "job", status: "available" };
      return page([{ id: "job", status: "available", created_at: "2026-10-01T00:00:00Z", expires_at: "2030-01-01T00:00:00Z" }]);
    });
    show(<MemberAccountExports makerspaceId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Request data export" }));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith(`${prefix}/exports`, { method: "POST" }));
    fireEvent.click(await screen.findByRole("button", { name: "Prepare download link" }));
    expect(await screen.findByRole("link", { name: "Download ZIP" })).toHaveAttribute("href", "https://files.example.test/signed");
  });

  it("makes no account requests when the feature and membership module are off", async () => {
    vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7 }, modules: ["member_accounts"], features: [] } as never);
    show(<Routes><Route path="*" element={<MemberAccountPage />} /></Routes>);
    expect(await screen.findByText("Account self-service is disabled for this makerspace.")).toBeVisible();
    expect(memberRequest).not.toHaveBeenCalled();
  });

  it("shows profile failures without submitting fabricated profile values", async () => {
    vi.mocked(memberRequest).mockRejectedValue(new Error("Profile unavailable"));
    show(<MemberAccountProfile makerspaceId={7} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Profile unavailable");
    expect(screen.queryByRole("button", { name: "Save profile" })).toBeNull();
  });

  it("replaces a stale profile draft when fresh server data arrives", async () => {
    const client = new QueryClient();
    vi.mocked(memberRequest).mockResolvedValue(profile);
    show(<MemberAccountProfile makerspaceId={7} />, "/", client);
    await screen.findByRole("textbox", { name: "Display name" });
    client.setQueryData(["member", "account", 7, "profile"], { ...profile, display_name: "New identity" });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("New identity"));
  });

  it("clears the previous identity's cached account before completing sign-in", async () => {
    const client = new QueryClient();
    client.setQueryData(["member", "account", 7, "profile"], { ...profile, display_name: "Previous person" });
    vi.mocked(refreshAccessToken).mockResolvedValue(false);
    vi.mocked(bootstrapTenant).mockResolvedValue({ makerspace: { id: 7 }, modules: ["membership", "member_accounts"], features: ["membership.self_service"] } as never);
    vi.mocked(memberRequest).mockImplementation(async (path) => path.endsWith("/profile") ? profile : path.includes("/sessions") ? page([]) : { status: "active", renewal_cancelled_at: null });
    show(<MemberAccountPage />, "/", client);
    fireEvent.click(await screen.findByRole("button", { name: "Complete sign in" }));
    expect(await screen.findByRole("textbox", { name: "Display name" })).toHaveValue("Ada");
    expect(screen.queryByDisplayValue("Previous person")).toBeNull();
  });

  it("resets the leave notice when navigating to another makerspace", async () => {
    vi.mocked(bootstrapTenant).mockImplementation(async ({ slug } = {}) => ({ makerspace: { id: slug === "b" ? 8 : 7 }, modules: ["membership", "member_accounts"], features: ["membership.self_service"] } as never));
    vi.mocked(memberRequest).mockImplementation(async (path) => path.endsWith("/profile") ? profile : path.includes("/sessions") ? page([]) : { status: "active", renewal_cancelled_at: null });
    show(<><Link to="/m/b/member/account">Other space</Link><Routes><Route path="/m/:slug/member/account" element={<MemberAccountPage />} /></Routes></>, "/m/a/member/account");
    fireEvent.click(await screen.findByRole("button", { name: "Leave makerspace" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Reason" }), { target: { value: "Moving" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm leave" }));
    await screen.findByText("You have left this makerspace. Your account remains available.");
    fireEvent.click(screen.getByRole("link", { name: "Other space" }));
    await screen.findByRole("button", { name: "Leave makerspace" });
    expect(screen.queryByText("You have left this makerspace. Your account remains available.")).toBeNull();
  });
});
