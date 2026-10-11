import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PublicEventDetailPage } from "./PublicEventDetailPage";
import { TenantProvider } from "../../lib/tenant";
import { StructuredApiError } from "../../lib/api";

const { tenantPublicRequest, tenantPublicRequestBlob } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn(), tenantPublicRequestBlob: vi.fn() }));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest, tenantPublicRequestBlob }));

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, throwOnError: false, experimental_prefetchInRender: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/m/lab/events/token"]}><TenantProvider><Link to="/m/lab/events/next">Next event</Link><Routes><Route path="/m/:slug/events/:publicToken" element={<PublicEventDetailPage />} /></Routes></TenantProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
beforeEach(() => { tenantPublicRequest.mockReset(); tenantPublicRequestBlob.mockReset(); });
const event = {
  public_token: "token", title: "Wood workshop", description: "Learn to carve", starts_at: "2026-11-01T10:00:00Z", ends_at: "2026-11-01T12:00:00Z", location: "Lab", capacity: 5,
  payment_amount: "25.00", currency: "inr", availability: "Available", registration_requires_approval: false, registration_open: true,
  registration_audience: "invite", custom_form: null, image_url: null, status: "published", series: null, tags: ["wood"], category: { id: 1, name: "Workshops", slug: "workshops" },
  ticket_types: [{ id: 3, name: "Public", amount: "25.00", audience: "public", spots_left: 5 }], promo_codes_enabled: true,
};

describe("public event detail", () => {
  it("starts a fresh registration form when navigating to another event", async () => {
    tenantPublicRequest.mockImplementation((_slug, path, options) => Promise.resolve(options?.method === "POST" ? { status: "registered" } : {
      ...event, public_token: path.includes("/next/") ? "next" : "token",
      title: path.includes("/next/") ? "Next workshop" : event.title,
      registration_audience: "accounts", ticket_types: [], promo_codes_enabled: false,
    }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Register" }));
    await screen.findByRole("heading", { name: "Registration received" });
    fireEvent.click(screen.getByRole("link", { name: "Next event" }));
    await screen.findByRole("heading", { name: "Next workshop" });
    expect(screen.queryByRole("heading", { name: "Registration received" })).toBeNull();
    expect(screen.getByRole("button", { name: "Register" })).toBeVisible();
  });

  it("removes a cached registration form after the detail read is refused", async () => {
    tenantPublicRequest.mockResolvedValue(event);
    const client = show();
    await screen.findByRole("heading", { name: event.title });
    tenantPublicRequest.mockRejectedValue(new StructuredApiError(404, { detail: "Not found" }));
    await client.invalidateQueries({ queryKey: ["public-event", "lab", "token"] });
    expect(await screen.findByRole("alert")).toHaveTextContent("Event not found.");
    expect(screen.queryByRole("heading", { name: event.title })).toBeNull();
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
  });

  it("renders share metadata and sends invite, ticket and promo in registration", async () => {
    tenantPublicRequest.mockImplementation((_slug, _path, options) => Promise.resolve(options?.method === "POST" ? { status: "registered" } : event));
    show();
    expect(await screen.findByRole("heading", { name: "Wood workshop" })).toBeVisible();
    expect(screen.getByText("Workshops")).toBeVisible();
    expect(document.querySelector('meta[property="og:title"]')).toHaveAttribute("content", "Wood workshop");
    fireEvent.change(screen.getByLabelText("Ticket type"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Invitation code"), { target: { value: "invite-secret" } });
    fireEvent.change(screen.getByLabelText("Promo code (optional)"), { target: { value: "promo-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await screen.findByRole("heading", { name: "Registration received" });
    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledWith("lab", "/public/lab/events/token/register/", expect.objectContaining({ body: JSON.stringify({ website: "", custom_answers: {}, invite_code: "invite-secret", promo_code: "promo-secret", ticket_type_id: 3 }) })));
  });
  it("shows an enumeration-safe missing event", async () => {
    tenantPublicRequest.mockRejectedValue(new StructuredApiError(404, { detail: "Not found" }));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Event not found.");
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
  });
  it("downloads calendar using configured tenant API transport", async () => {
    tenantPublicRequest.mockResolvedValue(event);
    tenantPublicRequestBlob.mockResolvedValue(new Blob(["BEGIN:VCALENDAR"]));
    URL.createObjectURL = vi.fn(() => "blob:calendar");
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Add to calendar" }));
    await waitFor(() => expect(tenantPublicRequestBlob).toHaveBeenCalledWith("lab", "/public/lab/events/token/calendar.ics"));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:calendar"));
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
  });
  it("blocks registration when only unavailable member tickets exist", async () => {
    tenantPublicRequest.mockResolvedValue({ ...event, ticket_types: [], ticket_selection_required: true });
    show();
    expect(await screen.findByText("No tickets are available for this account. Sign in or contact the organizers.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Register" })).toBeNull();
  });

  it("requests missing contact fields and retries the same account registration", async () => {
    let attempts = 0;
    tenantPublicRequest.mockImplementation((_slug, _path, options) => {
      if (options?.method !== "POST") return Promise.resolve({ ...event, registration_audience: "accounts", ticket_types: [], promo_codes_enabled: false });
      attempts += 1;
      if (attempts === 1) return Promise.reject(new StructuredApiError(400, { phone: ["This field cannot be blank."] }));
      if (attempts === 2) return Promise.reject(new StructuredApiError(400, { email: ["This field cannot be blank."] }));
      return Promise.resolve({ status: "registered" });
    });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Register" }));
    fireEvent.change(await screen.findByLabelText(/Contact phone/), { target: { value: "1234567890" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    fireEvent.change(await screen.findByLabelText(/Contact email/), { target: { value: "attendee@example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await screen.findByRole("heading", { name: "Registration received" });
    expect(tenantPublicRequest).toHaveBeenCalledWith("lab", "/public/lab/events/token/register/", expect.objectContaining({ body: JSON.stringify({ phone: "1234567890", email: "attendee@example.test", website: "", custom_answers: {} }) }));
  });

});
