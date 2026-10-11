import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PublicEventsPage } from "./PublicEventsPage";
import { TenantProvider } from "../../lib/tenant";

const { tenantPublicRequest } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest,
}));
vi.mock("./usePublicInventory", () => ({ useTenantBootstrap: () => ({ data: undefined }) }));

function event(title: string, amount: string, approval = false) {
  return {
    public_token: title, title, description: "", starts_at: "2026-11-01T10:00:00Z", ends_at: "2026-11-01T12:00:00Z",
    location: "Lab", capacity: 5, availability: "Available", payment_amount: amount, currency: "inr",
    registration_requires_approval: approval, registration_open: true, effective_registration_cutoff_at: null,
    image_url: null, status: "published", custom_form: null, series: null,
  };
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/m/lab/events"]}><TenantProvider><Routes><Route path="/m/:slug/events" element={<PublicEventsPage />} /></Routes></TenantProvider></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => { tenantPublicRequest.mockReset(); });

describe("public event prices", () => {
  it("excludes unavailable member-only tickets from the free-events filter", async () => {
    tenantPublicRequest.mockResolvedValue([
      { ...event("Members only", "0"), ticket_types: [], ticket_selection_required: true },
      event("Free public workshop", "0"),
    ]);
    show();
    await screen.findByRole("heading", { name: "Members only" });
    fireEvent.change(screen.getByLabelText("Filter"), { target: { value: "free" } });
    expect(screen.queryByRole("heading", { name: "Members only" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Free public workshop" })).toBeVisible();
  });

  it("shows paid and free prices before opening registration", async () => {
    tenantPublicRequest.mockResolvedValue([event("Paid", "125.50"), event("Free class", "0.00")]);
    show();
    expect(await screen.findByText("125.50 INR")).toBeVisible();
    expect(screen.getByText("Free", { selector: "dd" })).toBeVisible();
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("keeps the price visible beside an approval application form", async () => {
    tenantPublicRequest.mockResolvedValue([event("Reviewed", "80.00", true)]);
    show();
    await screen.findByText("80.00 INR");
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    const article = screen.getByRole("article");
    expect(within(article).getByText("80.00 INR")).toBeVisible();
    expect(within(article).getByRole("heading", { name: "Apply" })).toBeVisible();
  });
  it("filters by tenant category and tag and links each event detail", async () => {
    const wood = { ...event("Wood", "0"), category: { id: 1, name: "Workshops", slug: "workshops" }, tags: ["wood"] };
    const social = { ...event("Social", "0"), category: { id: 2, name: "Meetups", slug: "meetups" }, tags: ["community"] };
    tenantPublicRequest.mockResolvedValue([wood, social]);
    show();
    await screen.findByRole("heading", { name: "Wood" });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "workshops" } });
    expect(screen.queryByRole("heading", { name: "Social" })).toBeNull();
    expect(screen.getByRole("link", { name: "Wood" })).toHaveAttribute("href", "/m/lab/events/Wood");
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "community" } });
    expect(screen.queryByRole("heading", { name: "Wood" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Social" })).toBeVisible();
  });

});
