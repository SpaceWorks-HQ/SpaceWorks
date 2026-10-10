import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { MemberEventCancel } from "./MemberEventCancel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), staffRequest,
}));

function show(status = "registered") {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><MemberEventCancel makerspaceId={7} makerspaceSlug="lab" registrationId={11} status={status} /></QueryClientProvider>);
  return invalidate;
}

beforeEach(() => { staffRequest.mockReset(); });

describe("member event cancellation", () => {
  it.each(["pending_approval", "registered", "waitlisted"])("cancels %s and refreshes activity, availability and money", async (status) => {
    staffRequest.mockResolvedValue({ status: "cancelled" });
    const invalidate = show(status);
    fireEvent.click(screen.getByRole("button", { name: "Cancel registration" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/member/makerspaces/7/event-registrations/11/cancel/", { method: "POST", body: "{}" },
    ));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["member", "lab", "activity"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["public-events", "lab"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["member", "lab", "payments"] });
    expect(screen.getByRole("button", { name: "Registration cancelled" })).toBeDisabled();
  });

  it.each(["attended", "rejected", "cancelled"])("offers no cancellation for %s", (status) => {
    show(status);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("disables repeated submission while pending", async () => {
    staffRequest.mockReturnValue(new Promise(() => {}));
    show();
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("button", { name: "Cancelling..." })).toBeDisabled();
    expect(staffRequest).toHaveBeenCalledTimes(1);
  });

  it("shows a conflict and retains the cancellation control for retry", async () => {
    staffRequest.mockRejectedValue(new StructuredApiError(409, { detail: "This registration cannot be cancelled." }));
    const invalidate = show();
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("This registration cannot be cancelled.");
    expect(screen.getByRole("button", { name: "Cancel registration" })).toBeEnabled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("shows the expired deadline and directs the member to staff", () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><MemberEventCancel makerspaceId={7} makerspaceSlug="lab" registrationId={11} status="registered" canCancel={false} /></QueryClientProvider>);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("The cancellation deadline has passed. Contact staff.")).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("displays the cutoff in the member's local clock", () => {
    const client = new QueryClient();
    const cutoff = "2026-10-13T10:30:00Z";
    render(<QueryClientProvider client={client}><MemberEventCancel makerspaceId={7} makerspaceSlug="lab" registrationId={11} status="waitlisted" canCancel cutoffAt={cutoff} /></QueryClientProvider>);
    expect(screen.getByText(`Cancel before ${new Date(cutoff).toLocaleString()}.`)).toBeVisible();
  });
});
