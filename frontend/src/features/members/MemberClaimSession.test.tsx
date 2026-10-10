import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, memberRequest } from "../../lib/api";
import { hasClaimSession, MemberClaimSession } from "./MemberClaimSession";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn(), getAccessToken: vi.fn() }));
function show(modules = ["public_inventory"]) { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><MemberClaimSession slug="workshop" makerspaceId={3} modules={modules} geofenceEnabled={false} /></MemoryRouter></QueryClientProvider>); }
describe("MemberClaimSession", () => {
  beforeEach(() => { vi.clearAllMocks(); });
  it("recognizes a claim token for UI discovery without accepting malformed tokens", () => {
    vi.mocked(getAccessToken).mockReturnValue(`header.${btoa(JSON.stringify({ token_type: "claim_access" }))}.signature`); expect(hasClaimSession()).toBe(true);
    vi.mocked(getAccessToken).mockReturnValue("invalid"); expect(hasClaimSession()).toBe(false);
  });
  it("opens presence and shows a staff-witness waiver without forbidden global queries", async () => {
    vi.mocked(memberRequest).mockImplementation((path) => Promise.resolve(path.includes("waiver") ? { has_waiver: true, version: "v1", body: "Be careful" } : { active: false }) as ReturnType<typeof memberRequest>);
    show(); await screen.findByText("Start presence");
    expect(screen.getByRole("link", { name: "Browse tools" })).toHaveAttribute("href", "/m/workshop");
    expect(await screen.findByText("Be careful")).toBeVisible(); expect(screen.queryByText("Accept waiver")).toBeNull();
    fireEvent.click(screen.getByText("Start presence"));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/public/workshop/presence-sessions", { method: "POST", body: JSON.stringify({ duration_minutes: 120 }) }));
    expect(memberRequest).not.toHaveBeenCalledWith("/memberships/me"); expect(memberRequest).not.toHaveBeenCalledWith("/member/archived-payments");
  });
  it("shows an expired session error", async () => { vi.mocked(memberRequest).mockRejectedValue(new Error("Claim session is no longer active")); show(); expect(await screen.findByRole("alert")).toHaveTextContent("no longer active"); });
});
