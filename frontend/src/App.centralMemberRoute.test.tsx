/**
 * `/member` must exist on a CENTRAL deployment.
 *
 * The archived-payments recovery link lives inside `MemberArea`. A component test that renders
 * `MemberArea` directly proves the link renders -- it proves nothing about whether anyone can
 * REACH that component. On a central deployment the route table defined only `/m/:slug/member`,
 * so `/member` fell through to the not-found page, and a member whose only makerspace is
 * archived had no way in: their tenant URL no longer resolves and they cannot supply a slug
 * they can no longer discover.
 *
 * So this drives the real `App` router rather than the component.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useTenant } = vi.hoisted(() => ({ useTenant: vi.fn() }));

vi.mock("./lib/tenant", async () => {
  const actual = await vi.importActual<typeof import("./lib/tenant")>("./lib/tenant");
  return { ...actual, useTenant };
});

vi.mock("./features/members/MemberArea", () => ({
  // Stand-in: this test is about ROUTING, not about what the member area renders. It carries
  // the recovery Link because reaching that page by CLICK is the case that broke.
  // A REAL router Link, under MemoryRouter: navigating updates router context and leaves
  // `window.location` untouched, which is precisely the condition the stale
  // `window.location.pathname` read got wrong.
  MemberArea: () => (
    <div>
      member-area-rendered
      <Link to="/member/archived">View archived payments</Link>
    </div>
  ),
}));

vi.mock("./features/members/ArchivedPayments", () => ({
  ArchivedPayments: () => <div>archived-payments-rendered</div>,
}));

import App from "./App";

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("central deployment routing", () => {
  beforeEach(() => {
    useTenant.mockReset();
    useTenant.mockReturnValue({ mode: "central", loading: false, slug: "", makerspace: null });
  });

  it("routes /member to the member area rather than the not-found page", async () => {
    renderAt("/member");

    expect(await screen.findByText("member-area-rendered")).toBeVisible();
    expect(screen.queryByText("Page not found")).toBeNull();
  });

  it("reaches the recovery page by CLICK, not only by direct load", async () => {
    // The bypass branch read `window.location.pathname`, which a client-side navigation never
    // updates -- so the link rendered, the URL changed in router context, and the user landed
    // on the not-found page. Direct loads worked, which is what made it easy to miss.
    renderAt("/member");
    fireEvent.click(await screen.findByRole("link", { name: "View archived payments" }));

    expect(await screen.findByText("archived-payments-rendered")).toBeVisible();
    expect(screen.queryByText("Page not found")).toBeNull();
  });
});
