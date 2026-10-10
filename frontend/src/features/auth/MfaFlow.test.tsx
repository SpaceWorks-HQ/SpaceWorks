import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MfaFlow } from "./MfaFlow";
import { mfaRequest, type MfaChallenge } from "./mfaApi";

vi.mock("./mfaApi", () => ({ mfaRequest: vi.fn() }));
const request = vi.mocked(mfaRequest);
const challenge: MfaChallenge = { mfa_required: true, enrollment_required: false, challenge: "first-factor-proof", expires_in: 300 };
function mount(enrolling = false) {
  const complete = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}>
    <MfaFlow challenge={{ ...challenge, enrollment_required: enrolling }} onComplete={complete} onCancel={vi.fn()} />
  </QueryClientProvider>);
  return complete;
}

describe("MFA sign-in", () => {
  beforeEach(() => { request.mockReset(); });
  it("does not finish sign-in after a rejected second factor", async () => {
    request.mockRejectedValue(new Error("Invalid or expired MFA challenge."));
    const complete = mount();
    fireEvent.change(screen.getByLabelText("Authenticator or recovery code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or expired");
    expect(complete).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledWith("/auth/mfa/verify", { challenge: challenge.challenge, code: "123456" });
  });

  it("shows QR and manual key, then waits for recovery-code acknowledgement", async () => {
    request.mockResolvedValueOnce({ secret: "MANUALKEY", provisioning_uri: "otpauth://totp/SpaceWorks", qr_data_url: "data:image/png;base64,abc" });
    const result = { access: "verified-access", surface: "staff", user: {}, recovery_codes: ["saved-once-code"] };
    request.mockResolvedValueOnce(result);
    const complete = mount(true);
    fireEvent.click(screen.getByRole("button", { name: "Show enrollment QR and key" }));
    expect(await screen.findByText("MANUALKEY")).toBeInTheDocument();
    expect(screen.getByAltText("Scan to add SpaceWorks to your authenticator")).toHaveAttribute("src", "data:image/png;base64,abc");
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("saved-once-code")).toBeInTheDocument();
    expect(complete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "I saved my codes. Continue" }));
    await waitFor(() => expect(complete).toHaveBeenCalledWith(result));
  });

  it("accepts a recovery code without exposing enrollment controls", async () => {
    request.mockResolvedValue({ access: "verified-access", surface: "member", user: {} });
    const complete = mount();
    expect(screen.queryByText("Show enrollment QR and key")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Authenticator or recovery code"), { target: { value: "one-time-recovery" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(complete).toHaveBeenCalledTimes(1));
  });
});
