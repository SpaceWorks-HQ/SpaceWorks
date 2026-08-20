import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventAdmin, EventListResponse } from "../organizedEventsApi";
import { OrganizedEventsPanel } from "./OrganizedEventsPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const event: EventAdmin = {
  id: 73,
  makerspace_id: 19,
  title: "Community repair night",
  description: "Repair together.",
  starts_at: "2026-09-04T12:00:00Z",
  ends_at: "2026-09-04T14:00:00Z",
  location: "North workshop",
  location_kind: "indoor",
  custom_form: null,
  capacity: 30,
  payment_amount: "0.00",
  is_public: true,
  image_url: null,
  status: "draft",
  created_by_id: 5,
  created_at: "2026-08-20T10:00:00Z",
  updated_at: "2026-08-20T10:00:00Z",
  registration_counts: { registered: 4, attended: 2, waitlisted: 1, cancelled: 3 },
  organizers: [
    { name: "Repair Collective", slug: "repair-collective" },
    { name: "Open Tools", slug: "open-tools" },
  ],
};

const response = (overrides: Partial<EventListResponse> = {}): EventListResponse => ({
  count: 1,
  next: null,
  previous: null,
  results: [event],
  ...overrides,
});

function mockApi(list = response()) {
  staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith("/admin/organized-events/")) return list;
    if (path === `/admin/events/${event.id}/`) {
      if (init?.method === "PATCH") {
        return { ...event, ...JSON.parse(String(init.body)) };
      }
      return event;
    }
    if (path.includes("/registrations/")) {
      return { count: 0, next: null, previous: null, results: [] };
    }
    if (path.endsWith("/collaborators/")) return [];
    return [];
  });
}

function renderPanel(list = response()) {
  mockApi(list);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <OrganizedEventsPanel />
    </QueryClientProvider>,
  );
  return { ...view, queryClient };
}

// Braces matter: mockReset() RETURNS the mock, and vitest treats a function returned
// from beforeEach as a teardown callback -- so the concise-arrow form calls staffRequest()
// with no arguments after every test.
beforeEach(() => {
  staffRequest.mockReset();
});

describe("OrganizedEventsPanel", () => {
  it("requests the paginated endpoint with the server page size", async () => {
    renderPanel();

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/organized-events/?page=1&page_size=50",
    ));
  });

  it("renders a table skeleton while the request is pending", () => {
    staffRequest.mockReturnValue(new Promise(() => {}));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <OrganizedEventsPanel />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText("Loading organized events")).toBeVisible();
  });

  it("shows a retryable error state", async () => {
    staffRequest.mockRejectedValueOnce(new Error("Network unavailable"));
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <OrganizedEventsPanel />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Network unavailable")).toBeVisible();
    staffRequest.mockResolvedValueOnce(response({ results: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
  });

  it("uses the authority-neutral empty state", async () => {
    renderPanel(response({ count: 0, results: [] }));

    expect(await screen.findByRole("heading", {
      name: "No organized events -- this account has no active organization-managed events.",
    })).toBeVisible();
  });

  it("renders organizer names, slugs, and every registration count", async () => {
    renderPanel();

    expect(await screen.findByText("Repair Collective")).toBeVisible();
    expect(screen.getByText("(repair-collective)")).toBeVisible();
    expect(screen.getByText("Open Tools")).toBeVisible();
    expect(screen.getByText("10 total")).toBeVisible();
    expect(screen.getByText("4 registered · 2 attended")).toBeVisible();
    expect(screen.getByText("1 waitlisted · 3 cancelled")).toBeVisible();
  });

  it("drives previous and next controls from server links", async () => {
    renderPanel(response({ count: 100, next: "https://api.test/?page=2", previous: null }));
    const previous = await screen.findByRole("button", { name: "Previous" });
    const next = screen.getByRole("button", { name: "Next" });

    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();
    staffRequest.mockResolvedValueOnce(response({
      count: 100, next: null, previous: "https://api.test/?page=1",
    }));
    fireEvent.click(next);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/organized-events/?page=2&page_size=50",
    ));
    // Re-query rather than reusing the nodes captured above: the page-2 query key has no
    // cached data, so the whole pagination block unmounts while it loads and the old nodes
    // detach still carrying disabled="". No panel in this repo uses placeholderData, so the
    // unmount is the established behaviour rather than something to work around here.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    });
  });

  it("opens the row on its event and host makerspace, then refreshes organized data", async () => {
    const { queryClient } = renderPanel();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: event.title }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(`/admin/events/${event.id}/`));
    fireEvent.change(await screen.findByLabelText("Title"), {
      target: { value: "Updated repair night" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["events", event.makerspace_id, "list"],
    }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["events", "organized"] });
    await waitFor(() => expect(staffRequest.mock.calls.filter(
      ([path]) => path === "/admin/organized-events/?page=1&page_size=50",
    )).toHaveLength(2));
  });
});
