import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { memberRequest } from "../../lib/api";
import { MemberVerifierPanel } from "./MemberVerifierPanel";
vi.mock("../../lib/api", () => ({ memberRequest: vi.fn() }));
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}><MemberVerifierPanel makerspaceId={3} /></QueryClientProvider>); }
describe("MemberVerifierPanel", () => {
  beforeEach(() => { vi.mocked(memberRequest).mockReset(); });
  it("verifies and removes verification through the existing service endpoints", async () => {
    vi.mocked(memberRequest).mockResolvedValue({ display_name: "Guest" }); show();
    expect(screen.getByText("Verify member")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Membership ID"), { target: { value: "12" } });
    fireEvent.click(screen.getByText("Verify member")); await screen.findByText("Verification recorded for Guest.");
    expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/verification", { method: "POST", body: JSON.stringify({ membership_id: 12, verified: true }) });
    fireEvent.click(screen.getByText("Remove verification")); await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/verification", { method: "POST", body: JSON.stringify({ membership_id: 12, verified: false }) }));
    await screen.findByText("Verification removed for Guest.");
  });
  it("shows a scoped refusal without inventing a result", async () => { vi.mocked(memberRequest).mockRejectedValue(new Error("Not found")); show(); fireEvent.change(screen.getByLabelText("Membership ID"), { target: { value: "12" } }); fireEvent.click(screen.getByText("Verify member")); expect(await screen.findByRole("alert")).toHaveTextContent("Not found"); });
});
