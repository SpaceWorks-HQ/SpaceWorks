import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest } from "../../lib/api";
import { MemberProfilePanel, type MemberProfile } from "./MemberProfilePanel";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn() }));
vi.mock("../staff/ImageUploader", () => ({ ImageUploader: () => null }));
const profile: MemberProfile = { membership_id: 2, display_name: "Maker", is_visible: false, show_attended_events: false, headline: "", institution: "", bio: "", avatar_url: null, interests: [], languages: [], education: [], github_username: "", github_contributions: null, projects: [], activity: {} };
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemberProfilePanel makerspaceId={3} /></QueryClientProvider>); }
describe("MemberProfilePanel", () => {
  beforeEach(() => { vi.mocked(memberRequest).mockReset(); });
  it("loads and saves a member profile through the member session", async () => {
    vi.mocked(memberRequest).mockResolvedValue(profile); show();
    fireEvent.change(await screen.findByLabelText("Headline"), { target: { value: "Builds robots" } });
    fireEvent.click(screen.getByText("Save profile"));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/profile", expect.objectContaining({ method: "PUT", body: expect.stringContaining('"headline":"Builds robots"') })));
  });
  it("shows loading and a read error instead of disappearing", async () => {
    vi.mocked(memberRequest).mockRejectedValue(new Error("Profile unavailable")); show();
    expect(screen.getByText("Loading your profile…")).toBeVisible(); expect(await screen.findByRole("alert")).toHaveTextContent("Profile unavailable");
  });
});
