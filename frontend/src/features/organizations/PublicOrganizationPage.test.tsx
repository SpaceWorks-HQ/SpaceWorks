import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { PublicOrganizationPage } from "./PublicOrganizationPage";

vi.mock("./publicOrganizationsApi", () => ({
  usePublicOrganization: () => ({ data: { name: "Builders", logo_url: null, description: "", website: "" } }),
  usePublicOrganizationEvents: () => ({ data: {
    count: 2, next: null, previous: null, results: [
      { public_token: "paid", title: "Paid class", starts_at: "2026-11-01T10:00:00Z", ends_at: "2026-11-01T12:00:00Z", location: "", description: "", image_url: null, availability: "Available", payment_amount: "20.00", currency: "eur", host: { slug: "lab", name: "Lab" } },
      { public_token: "free", title: "Free class", starts_at: "2026-11-01T10:00:00Z", ends_at: "2026-11-01T12:00:00Z", location: "", description: "", image_url: null, availability: "Available", payment_amount: "0.00", currency: "eur", host: { slug: "lab", name: "Lab" } },
    ],
  } }),
}));

describe("organization public event prices", () => {
  it("renders host currency and free admission on the discovery cards", () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/organizations/builders"]}><Routes><Route path="/organizations/:organizationSlug" element={<PublicOrganizationPage />} /></Routes></MemoryRouter></QueryClientProvider>);
    expect(screen.getByText("20.00 EUR")).toBeVisible();
    expect(screen.getByText("Free", { selector: "dd" })).toBeVisible();
  });
});
