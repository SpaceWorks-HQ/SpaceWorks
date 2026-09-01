import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ArchivedPayments } from "./ArchivedPayments";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ArchivedPayments />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ArchivedPayments", () => {
  beforeEach(() => {
    staffRequest.mockReset();
  });

  it("renders the explicit empty state", async () => {
    staffRequest.mockResolvedValue([]);

    renderPage();

    expect(
      await screen.findByText("No charges outstanding from closed makerspaces."),
    ).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/member/archived-payments");
  });

  it("renders a pending charge with the existing checkout action", async () => {
    staffRequest.mockImplementation((path: string) => {
      if (path === "/member/archived-payments") {
        return Promise.resolve([
          {
            makerspace: { id: 7, slug: "closed-lab", name: "Closed Lab" },
            pending_count: 1,
            total_count: 1,
          },
        ]);
      }
      if (path === "/member/makerspaces/7/payments") {
        return Promise.resolve([
          {
            id: 41,
            subject_type: "booking",
            subject_label: "Laser cutter booking",
            status: "pending",
            checkout_url: "",
            created_at: "2026-08-11T08:00:00Z",
          },
        ]);
      }
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });

    renderPage();

    expect(await screen.findByText("Laser cutter booking")).toBeVisible();
    expect(screen.getByRole("listitem")).toHaveTextContent("pending");
    expect(
      screen.getByRole("button", { name: "Generate payment link" }),
    ).toBeEnabled();
  });
});
