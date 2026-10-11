import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PreferenceCentre } from "./PreferenceCentre";

const { memberRequest } = vi.hoisted(() => ({ memberRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest, getAccessToken: () => null }));

it("digest opt-in keeps the email topic enabled", async () => {
  const cell = { feature: "bookings", channel: "email", enabled: true, available: true, daily_digest: false, mandatory_events: [] };
  memberRequest.mockResolvedValue({ cells: [cell] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(<QueryClientProvider client={client}><PreferenceCentre makerspaceId={2} digests /></QueryClientProvider>);
  try {
    fireEvent.click(await screen.findByLabelText("bookings daily digest"));
    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/notifications/preferences/2", {
      method: "PATCH", body: JSON.stringify({ feature: "bookings", channel: "email", enabled: true, daily_digest: true }),
    }));
  } finally { unmount(); client.clear(); }
});
