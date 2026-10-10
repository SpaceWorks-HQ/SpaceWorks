import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StaffInvitationAcceptPage } from "./StaffInvitationAcceptPage";
import { mfaRequest } from "./mfaApi";

vi.mock("./mfaApi", () => ({ mfaRequest: vi.fn() }));
function mount() {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <StaffInvitationAcceptPage />
  </MemoryRouter></QueryClientProvider>);
}

describe("Staff invitation acceptance", () => {
  beforeEach(() => {
    vi.mocked(mfaRequest).mockReset();
    window.history.replaceState(null, "", "/staff-invitations/accept#token=private-token&space=the-lab");
  });

  it("submits bearer from the fragment and clears it after acceptance", async () => {
    vi.mocked(mfaRequest).mockResolvedValue({ detail: "Invitation accepted. Sign in with your email and password." });
    mount();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "current-password" } });
    fireEvent.change(screen.getByLabelText("Authenticator or recovery code (if your account has MFA)"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Invitation accepted");
    expect(mfaRequest).toHaveBeenCalledWith("/auth/staff-invitations/accept", {
      token: "private-token", makerspace_slug: "the-lab", password: "current-password", code: "123456",
    });
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("link", { name: "Sign in with your email" })).toHaveAttribute("href", "/admin");
  });

  it("renders the same generic refusal without suggesting whether an account exists", async () => {
    vi.mocked(mfaRequest).mockRejectedValue(new Error("Unable to accept this invitation. Check the link and credentials or contact the inviter."));
    mount();
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to accept this invitation");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
