import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PartnerEvents } from "./PartnerEvents";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
beforeEach(() => { staffRequest.mockReset(); });
const event = {
  id: 4, title: "Partner workshop", description: "", starts_at: "2026-11-01T10:00:00Z", ends_at: "2026-11-01T12:00:00Z", location: "Lab", custom_form: null,
  host_name: "Host", host_slug: "host", host_waiver: null, registration_open: true, registration_requires_approval: false, series: null,
  registration_audience: "invite", ticket_selection_required: true, promo_codes_enabled: true, currency: "inr", payment_amount: "0",
  ticket_types: [{ id: 3, name: "Public", amount: "25.00", audience: "public", spots_left: 5 }],
};
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><PartnerEvents makerspaceId={2} slug="partner" /></QueryClientProvider>);
}
describe("collaborative ticket registration", () => {
  it("collects the required ticket and invitation and submits optional promo", async () => {
    staffRequest.mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { status: "registered" } : [event]));
    show();
    fireEvent.click(await screen.findByRole("button", { name: /^Register/ }));
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Ticket type"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Invitation code"), { target: { value: "invite-secret" } });
    fireEvent.change(screen.getByLabelText("Promo code (optional)"), { target: { value: "promo-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/member/makerspaces/2/collaborative-events/4/register/", { method: "POST", body: JSON.stringify({ custom_answers: {}, host_waiver_accepted: false, ticket_type_id: 3, invite_code: "invite-secret", promo_code: "promo-secret" }) }));
  });
});
