import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest } from "../../lib/api";
import { MemberDirectory } from "./MemberDirectory";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn() }));
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemberDirectory makerspaceId={3} /></QueryClientProvider>); }
describe("MemberDirectory", () => {
  beforeEach(() => { vi.mocked(memberRequest).mockReset(); });
  it("loads an empty directory through the member session", async () => {
    vi.mocked(memberRequest).mockResolvedValue({ members: [], hidden_count: 1 }); show();
    expect(screen.getByText("Loading members…")).toBeVisible(); expect(await screen.findByText("Nobody has published a profile yet.")).toBeVisible();
    expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/directory");
    expect(screen.getByText("1 more member has not published a profile.")).toBeVisible();
  });
  it("shows a detail error after opening a published member", async () => {
    vi.mocked(memberRequest).mockImplementation((path) => path.endsWith("/2") ? Promise.reject(new Error("Profile no longer published")) : Promise.resolve({ members: [{ membership_id: 2, display_name: "Maker", headline: "Robots", avatar_url: null }], hidden_count: 0 }) as ReturnType<typeof memberRequest>);
    show(); fireEvent.click(await screen.findByRole("button", { name: /Maker/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Profile no longer published");
    expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/directory/2");
  });
  it("shows a list error", async () => { vi.mocked(memberRequest).mockRejectedValue(new Error("Directory unavailable")); show(); expect(await screen.findByRole("alert")).toHaveTextContent("Directory unavailable"); });
  it("gives nested identity cards a neutral profile base instead of stacking tints", async () => {
    vi.mocked(memberRequest).mockImplementation(async (path) => path.endsWith("/2")
      ? { institution: "Neutral profile", bio: "Maker bio", interests: [], languages: [], education: [], achievements: [], projects: [{ id: 2, title: "Mint project", description: "Project details", links: [], image_url: null }] }
      : { members: [{ membership_id: 2, display_name: "Maker", headline: "Robots", avatar_url: null }], hidden_count: 0 });
    show();
    fireEvent.click(await screen.findByRole("button", { name: /Maker/ }));
    const profile = (await screen.findByText("Neutral profile")).parentElement;
    expect(profile).toHaveClass("desk-panel");
    expect(profile).not.toHaveClass("bg-secondary/10");
    expect(profile?.parentElement).not.toHaveClass("bg-secondary/15");
    expect(screen.getByText("Mint project").closest("article")).toHaveClass("bg-success/15");
  });
});
