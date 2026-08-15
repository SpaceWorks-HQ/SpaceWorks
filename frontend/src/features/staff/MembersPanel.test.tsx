import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
