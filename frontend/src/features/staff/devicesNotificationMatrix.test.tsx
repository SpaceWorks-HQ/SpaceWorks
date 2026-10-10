import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NotificationChannelPreferences } from "./NotificationChannelPreferences";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

it("renders devices default-off and saves an explicit opt-in", async () => {
  const rules = { catalog: [], mutes: [], channels: [{ key: "email", label: "Email" }],
    features: [{ key: "devices", label: "Devices", events: ["offline", "recovered"] }],
    preferences: [{ feature: "devices", channel: "email", enabled: false, source: "default" as const }] };
  staffRequest.mockResolvedValue(rules);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><NotificationChannelPreferences makerspaceId={7} rules={rules} /></QueryClientProvider>);
  const toggle = screen.getByRole("checkbox");
  expect(toggle).not.toBeChecked();
  fireEvent.click(toggle);
  await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/notification-rules", {
    method: "PATCH", body: JSON.stringify({ preferences: [{ feature: "devices", channel: "email", enabled: true }] }),
  }));
});
