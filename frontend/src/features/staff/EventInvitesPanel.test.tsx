import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EventInvitesPanel } from "./EventInvitesPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, throwOnError: false, experimental_prefetchInRender: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><EventInvitesPanel eventId={4} /></QueryClientProvider>);
}
beforeEach(() => { staffRequest.mockReset(); });

describe("event invitations", () => {
  it("creates a bounded invitation, reveals its code once and revokes it", async () => {
    const row = { id: 8, max_uses: 2, uses: 0, expires_at: null, revoked_at: null };
    staffRequest.mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { ...row, code: "one-time-code" } : { count: 1, next: null, previous: null, results: [row] }));
    show();
    await screen.findByRole("button", { name: "Revoke invitation 8" });
    fireEvent.change(screen.getByLabelText("Maximum uses"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText("one-time-code")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/admin/events/4/invites/", expect.objectContaining({ body: JSON.stringify({ email: "", max_uses: 2, expires_at: null }) }));
    fireEvent.click(screen.getByRole("button", { name: "Hide code" }));
    expect(screen.queryByText("one-time-code")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Revoke invitation 8" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/event-invites/8/revoke/", { method: "POST", body: "{}" }));
  });
  it("shows failure without revealing a code", async () => {
    staffRequest.mockRejectedValue(new Error("Access refused"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Access refused");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
