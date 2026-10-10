import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersPanel } from "./MembersPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const roster = {
  count: 1,
  next: null,
  previous: null,
  results: [{
    id: 7,
    status: "active",
    user: { id: 9, username: "walkin", email: "", display_name: "Walk In" },
    assigned_role: { id: 1, name: "Member", slug: "member" },
    can_refer: false,
    can_verify: false,
    verified_at: null,
    activated_at: null,
    revoked_at: null,
    revocation_reason: "",
    waiver_accepted_at: null,
    waiver_version_accepted: null,
    waiver_current: false,
    waiver_required: true,
    payment: null,
  }],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MembersPanel makerspaceId={3} membershipEnabled={false} />
    </QueryClientProvider>,
  );
}

describe("MembersPanel waiver controls", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve(roster);
      if (url.includes("presence-sessions")) return Promise.resolve([]);
      if (url.endsWith("/roles")) return Promise.resolve([{ id: 1, name: "Member" }]);
      return Promise.resolve({});
    });
  });

  it("keeps core waiver controls available when community membership is disabled", async () => {
    renderPanel();

    expect(await screen.findByText("Record witnessed acceptance")).toBeInTheDocument();
    expect(screen.getByText("Publish waiver")).toBeInTheDocument();
    expect(screen.queryByText("Can refer")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Record witnessed acceptance"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/memberships/7/waiver/witness",
      { method: "POST", body: JSON.stringify({}) },
    ));
  });
});

const pendingRequests = {
  count: 2,
  next: null,
  previous: null,
  results: [
    { id: 41, kind: "request", state: "requested", invite_email: "joiner@example.test", user: { id: 5, username: "joiner" }, assigned_role: null, decision_note: "", created_at: "2026-10-01T00:00:00Z", decided_at: null },
    { id: 42, kind: "invite", state: "invited", invite_email: "staff@example.test", user: null, assigned_role: { id: 2, name: "Inventory Manager" }, decision_note: "", created_at: "2026-10-01T00:00:00Z", decided_at: null },
  ],
};

function renderWith(membershipEnabled: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MembersPanel makerspaceId={3} membershipEnabled={membershipEnabled} />
    </QueryClientProvider>,
  );
}

describe("MembersPanel request queue", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve(roster);
      if (url.startsWith("/admin/membership-requests?")) return Promise.resolve(pendingRequests);
      if (url.includes("invitation-requests") || url.includes("membership-plans")) return Promise.resolve([]);
      if (url.includes("presence-sessions")) return Promise.resolve([]);
      if (url.endsWith("/roles")) return Promise.resolve([{ id: 1, name: "Member" }, { id: 2, name: "Inventory Manager" }]);
      return Promise.resolve({});
    });
  });

  it("approves with the role the dropdown shows, without the dropdown being touched", async () => {
    renderWith(true);

    fireEvent.click(await screen.findByText("Approve"));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-requests/41/approve",
      { method: "POST", body: JSON.stringify({ role_id: 1 }) },
    ));
  });

  it("invites with the shown role, and posts a changed one", async () => {
    renderWith(true);
    fireEvent.change(await screen.findByLabelText("Invite email"), { target: { value: "new@example.test" } });
    fireEvent.click(screen.getByText("Invite"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/3/membership-invitations",
      { method: "POST", body: JSON.stringify({ invite_email: "new@example.test", role_id: 1 }) },
    ));

    fireEvent.change(screen.getByLabelText("Invite role"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Invite email"), { target: { value: "other@example.test" } });
    fireEvent.click(screen.getByText("Invite"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/3/membership-invitations",
      { method: "POST", body: JSON.stringify({ invite_email: "other@example.test", role_id: 2 }) },
    ));
  });

  it("lists invitations with the module off and lets staff cancel one", async () => {
    renderWith(false);

    fireEvent.click(await screen.findByText("Cancel invitation"));
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Invitation no longer needed" } });
    fireEvent.click(screen.getByText("Confirm decision"));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/membership-requests/42/revoke",
      { method: "POST", body: JSON.stringify({ reason: "Invitation no longer needed" }) },
    ));
  });

  it("sends an optional plan with approval", async () => {
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve(roster);
      if (url.startsWith("/admin/membership-requests?")) return Promise.resolve(pendingRequests);
      if (url.includes("membership-plans")) return Promise.resolve([{ id: 8, name: "Monthly", amount: "5", currency: "usd", is_active: true }]);
      if (url.endsWith("/roles")) return Promise.resolve([{ id: 1, name: "Member" }]);
      return Promise.resolve([]);
    });
    renderWith(true);
    await within(screen.getByLabelText("Approval plan (optional)")).findByRole("option", { name: /Monthly/ });
    fireEvent.change(screen.getByLabelText("Approval plan (optional)"), { target: { value: "8" } });
    fireEvent.click(await screen.findByText("Approve"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/membership-requests/41/approve", { method: "POST", body: JSON.stringify({ role_id: 1, plan_id: 8 }) }));
  });

  it("posts decline and revoke reasons only after confirmation", async () => {
    renderWith(true);
    fireEvent.click(await screen.findByText("Decline"));
    expect(staffRequest).not.toHaveBeenCalledWith("/admin/membership-requests/41/revoke", expect.anything());
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Full" } });
    fireEvent.click(screen.getByText("Confirm decision"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/membership-requests/41/revoke", { method: "POST", body: JSON.stringify({ reason: "Full" }) }));
    await waitFor(() => expect(screen.queryByLabelText("Decision reason")).toBeNull());
    fireEvent.click(screen.getByText("Revoke"));
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "Moved away" } });
    fireEvent.click(screen.getByText("Confirm decision"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/memberships/7/revoke", { method: "POST", body: JSON.stringify({ reason: "Moved away" }) }));
  });

  it("fetches both second pages without reusing page-one rows", async () => {
    staffRequest.mockImplementation((url: string) => {
      if (url.startsWith("/admin/memberships?")) return Promise.resolve(url.includes("page=2") ? { count: 25, next: null, previous: "previous", results: [] } : { ...roster, next: "next" });
      if (url.startsWith("/admin/membership-requests?")) return Promise.resolve(url.includes("page=2") ? { count: 25, next: null, previous: "previous", results: [] } : { ...pendingRequests, next: "next" });
      if (url.endsWith("/roles")) return Promise.resolve([{ id: 1, name: "Member" }]);
      return Promise.resolve([]);
    });
    renderWith(false);
    await screen.findByText("Walk In");
    fireEvent.click(screen.getByText("Next members"));
    expect(await screen.findByText("No members on this page.")).toBeVisible();
    fireEvent.click(screen.getByText("Next requests"));
    expect(await screen.findByText("No membership requests on this page.")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/admin/memberships?makerspace_id=3&page=2");
    expect(staffRequest).toHaveBeenCalledWith("/admin/membership-requests?makerspace_id=3&page=2");
  });
});
