import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PreferenceCentre } from "./PreferenceCentre";
import { DeliveryLogScreen } from "./DeliveryLogScreen";

const { memberRequest, staffRequest } = vi.hoisted(() => ({ memberRequest: vi.fn(), staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest, staffRequest, getAccessToken: () => null }));

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  return () => { result.unmount(); client.clear(); };
}

beforeEach(() => { memberRequest.mockReset(); staffRequest.mockReset(); });

describe("personal preferences", () => {
  it("saves a family opt-out while keeping safety messaging visible and disabled channels locked", async () => {
    let enabled = true;
    memberRequest.mockImplementation(async (_path: string, options?: { method?: string }) => {
      if (options) enabled = false;
      return { cells: [
        { feature: "hardware_requests", channel: "email", enabled, available: true, mandatory_events: ["return_reminder"] },
        { feature: "events", channel: "in_app", enabled: false, available: false, mandatory_events: [] },
      ] };
    });
    const cleanup = mount(<PreferenceCentre makerspaceId={7} />);
    try {
      const toggles = await screen.findAllByRole("checkbox");
      expect(toggles[1]).toBeDisabled();
      fireEvent.click(toggles[0]);
      await waitFor(() => expect(toggles[0]).not.toBeChecked());
      expect(memberRequest).toHaveBeenLastCalledWith("/notifications/preferences/7", {
        method: "PATCH", body: JSON.stringify({ feature: "hardware_requests", channel: "email", enabled: false }),
      });
      expect(screen.getByText(/Safety emails stay enabled: return reminder/)).toBeVisible();
    } finally { cleanup(); }
  });

  it("shows save errors without changing cached preferences", async () => {
    memberRequest.mockImplementation(async (_path: string, options?: unknown) => {
      if (options) throw new Error("Unable to save preference");
      return { cells: [{ feature: "bookings", channel: "email", enabled: true, available: true, mandatory_events: [] }] };
    });
    const cleanup = mount(<PreferenceCentre makerspaceId={7} />);
    try {
      fireEvent.click(await screen.findByRole("checkbox"));
      expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save preference");
      expect(screen.getByRole("checkbox")).toBeChecked();
    } finally { cleanup(); }
  });
});

it("retries with the displayed generation and sends the default test only to oneself", async () => {
  const failed = { id: 42, kind: "email", channel: "email", feature: "bookings", event: "confirmed",
    destination_id: null, destination_label: "Email", status: "failed", error: "Delivery failed",
    attempts: 2, retry_generation: 3, created_at: "2026-10-11T00:00:00Z", sent_at: null };
  staffRequest.mockImplementation(async (path: string, options?: { method?: string }) => {
    if (path.endsWith("/retry")) return { ...failed, status: "pending" };
    if (path.endsWith("/delivery-test")) return { kind: "email", id: 43, status: "pending" };
    if (path.includes("notification-destinations")) return [];
    return { count: options ? 0 : 1, next: null, previous: null, results: path.includes("delivery-logs") ? [failed] : [] };
  });
  const cleanup = mount(<DeliveryLogScreen makerspaceId={7} />);
  try {
    fireEvent.click(await screen.findByRole("button", { name: "Retry failed delivery" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/integrations/makerspace/7/delivery-logs/email/42/retry", {
      method: "POST", body: JSON.stringify({ generation: 3 }),
    }));
    fireEvent.click(screen.getByRole("button", { name: "Send test" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/integrations/makerspace/7/delivery-test", {
      method: "POST", body: "{}",
    }));
    expect(await screen.findByRole("status")).toHaveTextContent("Test email #43: pending");
  } finally { cleanup(); }
});
