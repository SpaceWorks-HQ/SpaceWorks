import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PublicEventsPage } from "../inventory/PublicEventsPage";
import { PublicBookingsPage } from "../bookings/PublicBookingsPage";
import { TenantProvider } from "../../lib/tenant";
import { expectNoA11yViolations } from "../../test/axe";

const { request, state } = vi.hoisted(() => ({ request: vi.fn(), state: { timeZone: "" } }));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest: request }));
vi.mock("../inventory/usePublicInventory", () => ({ useTenantBootstrap: () => ({ data: state.timeZone ? { makerspace: { timezone: state.timeZone }, branding: {}, theme: {}, modules: [] } : undefined }) }));
vi.mock("../bookings/PublicBookingForm", () => ({ PublicBookingForm: () => <h3>Booking form</h3> }));
function Location() {
  const location = useLocation(); const navigate = useNavigate();
  return <><output>{location.search}</output><button onClick={() => navigate(-1)}>Back</button></>;
}
function show(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[path]}><TenantProvider><Routes>
      <Route path="/m/:slug/events" element={<PublicEventsPage />} />
      <Route path="/m/:slug/bookings" element={<PublicBookingsPage />} />
    </Routes><Location /></TenantProvider></MemoryRouter>
  </QueryClientProvider>) };
}
function event(title: string, amount = "0.00", month = "11") {
  return { public_token: title, title, description: "Workshop", location: "Lab", starts_at: `2026-${month}-01T10:00:00`, ends_at: `2026-${month}-01T12:00:00`,
    payment_amount: amount, currency: "inr", availability: "Available", capacity: 8, registration_open: true,
    registration_requires_approval: false, status: "published", custom_form: null, series: null, image_url: null };
}
function space(name: string, kind = "bench", published = true, names = false) {
  return { public_token: name, name, description: "Bookable workspace", location: "Lab", kind, capacity: 8, approval_mode: "approve",
    custom_form: null, image_url: "", show_public_availability: published, show_public_booker_names: names };
}
beforeEach(() => { state.timeZone = ""; request.mockReset(); vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-11T00:00:00Z")); });
afterEach(() => { vi.restoreAllMocks(); });

it("restores event search/free/month filters from a deep link and renders the month calendar", async () => {
  request.mockResolvedValue([event("Woodwork"), event("Woodwork paid", "25"), event("Electronics"), event("Woodwork December", "0", "12")]);
  const view = show("/m/lab/events?q=wood&filter=free&view=calendar&month=2026-11");
  expect(await screen.findByRole("heading", { name: "Woodwork" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Woodwork paid" })).toBeNull();
  expect(screen.queryByRole("heading", { name: "Woodwork December" })).toBeNull();
  expect(screen.getByRole("searchbox", { name: "Search events" })).toHaveValue("wood");
  expect(screen.getByRole("table")).toHaveAccessibleName(/Upcoming public events/);
  const eventLink = within(screen.getByRole("table")).getByRole("link", { name: "Woodwork" });
  expect(eventLink).toHaveAttribute("href", "#event-Woodwork");
  expect(document.querySelector("#event-Woodwork")).toHaveAttribute("tabindex", "-1");
  await expectNoA11yViolations(view.container);
});

it("changing discovery filters updates the URL and Back restores prior results", async () => {
  request.mockResolvedValue([event("Woodwork"), event("Electronics")]);
  show("/m/lab/events");
  await screen.findByRole("heading", { name: "Woodwork" });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "no-match" } });
  expect(screen.getByRole("heading", { name: "No matching events" })).toBeVisible();
  expect(screen.getByText("?q=no-match")).toBeVisible();
  fireEvent.click(screen.getByText("Back"));
  expect(screen.getByRole("heading", { name: "Woodwork" })).toBeVisible();
});

it("filters bookable spaces by name and kind and reuses the booking form", async () => {
  request.mockResolvedValue([space("Bench A"), space("Meeting A", "meeting")]);
  show("/m/lab/bookings?q=a&filter=meeting");
  expect(await screen.findByRole("heading", { name: "Meeting A" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Bench A" })).toBeNull();
  fireEvent.click(screen.getByText("Choose a time"));
  expect(screen.getByRole("heading", { name: "Booking form" })).toBeVisible();
});

it("shows busy intervals without exposing disabled booker names or promising availability", async () => {
  request.mockImplementation(async (_slug, path) => path.includes("availability") ? { availability: [{ starts_at: "2026-11-02T10:00:00", ends_at: "2026-11-02T12:00:00", booker_name: "Private person" }] } : [space("Bench A")]);
  const view = show("/m/lab/bookings?view=calendar&month=2026-11");
  expect(await screen.findByRole("table")).toHaveAccessibleName(/Bench A published bookings/);
  expect(screen.getByText(/Booked/)).toBeVisible();
  expect(screen.queryByText(/Private person/)).toBeNull();
  expect(screen.getByText(/Empty dates do not guarantee/)).toBeVisible();
  await expectNoA11yViolations(view.container);
});

it("does not query hidden availability, and explains the publication policy", async () => {
  request.mockResolvedValue([space("Private calendar", "bench", false)]);
  show("/m/lab/bookings?view=calendar&month=2026-11");
  expect(await screen.findByText(/Availability is not published/)).toBeVisible();
  expect(request.mock.calls.some(([, path]) => path.includes("availability"))).toBe(false);
  expect(screen.queryByRole("table")).toBeNull();
});

it("filters event months using the makerspace timezone from bootstrap", async () => {
  state.timeZone = "Asia/Kolkata";
  request.mockResolvedValue([{ ...event("Midnight workshop"), starts_at: "2026-10-31T20:00:00Z", ends_at: "2026-10-31T21:00:00Z" }]);
  show("/m/lab/events?view=calendar&month=2026-11");
  expect(await screen.findByRole("heading", { name: "Midnight workshop" })).toBeVisible();
  expect(screen.getByRole("table")).toHaveAccessibleName(/Asia\/Kolkata/);
});

it.each(["events", "bookings"])("shows a %s refresh error without claiming there are no matches", async (surface) => {
  request.mockResolvedValue(surface === "events" ? [event("Workshop")] : [space("Bench A")]);
  const view = show(`/m/lab/${surface}`);
  await screen.findByRole("heading", { name: surface === "events" ? "Workshop" : "Bench A" });
  const { StructuredApiError } = await import("../../lib/api");
  request.mockRejectedValue(new StructuredApiError(400, { module: ["disabled"] }));
  await act(async () => { await view.client.invalidateQueries(); });
  await waitFor(() => expect(screen.getByRole("heading", { name: surface === "events" ? "Events are not enabled" : "Bookings are not enabled" })).toBeVisible());
  expect(screen.queryByRole("heading", { name: /No matching/ })).toBeNull();
  expect(screen.queryByRole("heading", { name: surface === "events" ? "Workshop" : "Bench A" })).toBeNull();
});
