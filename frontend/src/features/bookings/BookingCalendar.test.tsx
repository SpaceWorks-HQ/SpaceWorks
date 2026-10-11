import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { BookingCalendar } from "./BookingCalendar";

const { memberRequest } = vi.hoisted(() => ({ memberRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest, getAccessToken: () => null }));

it("shows a newly issued private link and clears it after revocation", async () => {
  let enabled = false;
  memberRequest.mockImplementation(async (_path: string, options?: { method: string }) => {
    if (options?.method === "POST") { enabled = true; return { feed_url: "https://example.test/private.ics" }; }
    if (options?.method === "DELETE") { enabled = false; return; }
    return { enabled };
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(<QueryClientProvider client={client}><BookingCalendar slug="forge" /></QueryClientProvider>);
  try {
    await waitFor(() => expect(screen.getByRole("button", { name: "Create calendar link" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Create calendar link" }));
    expect(await screen.findByLabelText("Private calendar URL")).toHaveValue("https://example.test/private.ics");
    fireEvent.click(await screen.findByRole("button", { name: "Revoke calendar link" }));
    await waitFor(() => expect(screen.queryByLabelText("Private calendar URL")).toBeNull());
    expect(memberRequest).toHaveBeenCalledWith("/public/forge/my-bookings/calendar/", { method: "DELETE" });
  } finally { unmount(); client.clear(); }
});
