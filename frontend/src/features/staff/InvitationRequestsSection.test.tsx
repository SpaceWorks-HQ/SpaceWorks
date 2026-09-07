import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../test/axe";
import { InvitationRequestsSection, sortInvitationRequests } from "./InvitationRequestsSection";
import type { InvitationRequest } from "./membershipPlansApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const rows: InvitationRequest[] = [
  { id: 1, name: "Grace Hopper", email: "grace@example.com", phone: "", message: "", status: "invited", handled_by: 4, handled_at: "2026-08-03T00:00:00Z", created_at: "2026-08-03T00:00:00Z" },
  { id: 2, name: "Ada Lovelace", email: "ada@example.com", phone: "+1 555 0100", message: "I run the local robotics club.", status: "pending", handled_by: null, handled_at: null, created_at: "2026-08-01T00:00:00Z" },
  { id: 3, name: "", email: "linus@example.com", phone: "", message: "", status: "pending", handled_by: null, handled_at: null, created_at: "2026-08-02T00:00:00Z" },
];

const roles = [{ id: 10, name: "Member" }, { id: 11, name: "Volunteer" }];

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <InvitationRequestsSection makerspaceId={7} roles={roles} />
    </QueryClientProvider>,
  );
  return { ...view, invalidate };
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) =>
    options?.method === "POST" ? { ...rows[1], status: "invited" } : rows);
});

describe("InvitationRequestsSection", () => {
  it("orders pending requests first (newest first within a status)", () => {
    expect(sortInvitationRequests(rows).map((row) => row.id)).toEqual([3, 2, 1]);
  });

  it("lists the queue with controls only on pending rows", async () => {
    const { container } = renderSection();

    expect(await screen.findByText("Ada Lovelace")).toBeVisible();
    expect(screen.getByText("I run the local robotics club.")).toBeVisible();
    expect(screen.getByText(/2 pending/)).toBeVisible();
    // Grace is already invited: no Invite/Decline for her, so two of each remain.
    expect(screen.getAllByRole("button", { name: "Invite" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Decline" })).toHaveLength(2);

    await expectNoA11yViolations(container);
  });

  it("invites with the chosen role and declines through their endpoints", async () => {
    const { invalidate } = renderSection();
    await screen.findByText("Ada Lovelace");

    fireEvent.change(screen.getByRole("combobox", { name: "Role for Ada Lovelace" }), { target: { value: "11" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Invite" })[1]);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/invitation-requests/2/invite",
      { method: "POST", body: JSON.stringify({ role_id: 11 }) },
    ));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["invitation-requests", 7] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["members", 7] });

    fireEvent.click(screen.getAllByRole("button", { name: "Decline" })[0]);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/invitation-requests/3/decline",
      { method: "POST" },
    ));
  });
});
