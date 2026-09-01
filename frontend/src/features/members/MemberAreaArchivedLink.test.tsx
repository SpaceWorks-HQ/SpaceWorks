/**
 * The archived-payments link must survive a FAILED tenant bootstrap.
 *
 * A member whose only makerspace is archived cannot bootstrap that tenant -- `resolve_frontend`
 * excludes archived spaces -- and `/memberships/me` returns them no memberships. If the link
 * rendered only inside a successfully-bootstrapped member area, the people the recovery route
 * exists for would be the exact people who could never find it, and would have to guess the URL.
 *
 * So this pins the discoverability contract directly: bootstrap rejects, memberships come back
 * empty, and the link is still on the page.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest, bootstrapTenant, refreshAccessToken, fetchMe } = vi.hoisted(() => ({
  staffRequest: vi.fn(),
  bootstrapTenant: vi.fn(),
  refreshAccessToken: vi.fn(),
  fetchMe: vi.fn(),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest, bootstrapTenant, refreshAccessToken, fetchMe };
});

import { StructuredApiError } from "../../lib/api";
import { MemberArea } from "./MemberArea";

function renderArea() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MemberArea />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MemberArea archived-payments discoverability", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    bootstrapTenant.mockReset();
    refreshAccessToken.mockReset();
    fetchMe.mockReset();
    refreshAccessToken.mockResolvedValue(undefined);
    fetchMe.mockResolvedValue({});
  });

  it("still offers the recovery link when the tenant cannot be bootstrapped", async () => {
    bootstrapTenant.mockRejectedValue(new Error("Makerspace not found."));
    staffRequest.mockImplementation((path: string) => {
      // The shape a member with only an archived space actually gets back.
      if (path === "/memberships/me") return Promise.resolve({ memberships: [], requests: [] });
      // Must be the real payload shape: the component does
      // `invitations.data?.invitations.filter(...)`, so a bare [] throws during render.
      if (path === "/memberships/invitations") return Promise.resolve({ invitations: [] });
      if (path === "/member/archived-payments") {
        return Promise.resolve([
          {
            makerspace: { id: 7, slug: "closed-space", name: "Closed Space" },
            pending_count: 1,
            total_count: 3,
          },
        ]);
      }
      return Promise.resolve([]);
    });

    renderArea();

    const link = await screen.findByRole("link", { name: "View archived payments" });
    expect(link).toBeVisible();
    expect(link).toHaveAttribute("href", "/member/archived");
  });

  it("still offers the recovery link to a SIGNED-OUT visitor", async () => {
    // The worst case: bootstrap fails AND `/memberships/me` 401s, so there is no membership
    // data, no policy, and therefore no sign-in call to action either. Without an
    // unconditional link the member has nowhere to go but a guessed URL.
    bootstrapTenant.mockRejectedValue(new Error("Makerspace not found."));
    staffRequest.mockImplementation(() =>
      Promise.reject(new StructuredApiError(401, { detail: "Authentication required." })),
    );

    renderArea();

    const link = await screen.findByRole("link", { name: "View archived payments" });
    expect(link).toHaveAttribute("href", "/member/archived");
  });
});
