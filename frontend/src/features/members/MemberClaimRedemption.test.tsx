import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest, setAccessToken } from "../../lib/api";
import { MemberClaimRedemption } from "./MemberClaimRedemption";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn(), setAccessToken: vi.fn() }));
function show() { render(<QueryClientProvider client={new QueryClient()}><MemberClaimRedemption slug="workshop" /></QueryClientProvider>); }
describe("MemberClaimRedemption", () => {
  beforeEach(() => vi.clearAllMocks());
  it("redeems for this space and installs the bounded access token", async () => {
    vi.mocked(memberRequest).mockResolvedValue({ access: "temporary-session" }); show();
    expect(screen.getByText("Redeem claim code")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Claim code"), { target: { value: " MC1-test " } }); fireEvent.click(screen.getByText("Redeem claim code"));
    await waitFor(() => expect(setAccessToken).toHaveBeenCalledWith("temporary-session"));
    expect(memberRequest).toHaveBeenCalledWith("/auth/claim/redeem", { method: "POST", body: JSON.stringify({ makerspace_slug: "workshop", code: "MC1-test" }) });
  });
  it("shows invalid-code errors without creating a session", async () => {
    vi.mocked(memberRequest).mockRejectedValue(new Error("Invalid or expired claim code")); show();
    fireEvent.change(screen.getByLabelText("Claim code"), { target: { value: "bad" } }); fireEvent.click(screen.getByText("Redeem claim code"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or expired"); expect(setAccessToken).not.toHaveBeenCalled();
  });
});
