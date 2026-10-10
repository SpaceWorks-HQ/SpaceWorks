import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MakerspaceReminderSettings } from "./MakerspaceReminderSettings";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), staffRequest,
}));

const makerspace = { id: 7, name: "Studio", slug: "studio", enabled_modules: ["events", "bookings"] } as Makerspace;

function mount(settings: Makerspace = makerspace) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidation = vi.spyOn(client, "invalidateQueries");
  return { ...render(<QueryClientProvider client={client}>
    <MakerspaceReminderSettings makerspace={makerspace} settings={settings} loading={false} />
  </QueryClientProvider>), invalidation };
}

beforeEach(() => { staffRequest.mockReset(); staffRequest.mockResolvedValue(makerspace); });

describe("MakerspaceReminderSettings", () => {
  it("saves lead hours and refreshes makerspace server state", async () => {
    const { invalidation } = mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Event reminder lead hours" }), { target: { value: "24, 2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save event reminders" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
      method: "PATCH", body: JSON.stringify({ event_reminder_lead_hours: [24, 2] }),
    }));
    expect(invalidation).toHaveBeenCalledWith({ queryKey: ["makerspace-settings", 7] });
  });

  it("allows an empty booking policy to disable reminders", async () => {
    mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Booking reminder lead hours" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save booking reminders" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
      method: "PATCH", body: JSON.stringify({ booking_reminder_lead_hours: [] }),
    }));
  });

  it("rejects duplicate offsets without submitting", () => {
    mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Event reminder lead hours" }), { target: { value: "24, 24" } });
    fireEvent.click(screen.getByRole("button", { name: "Save event reminders" }));
    expect(screen.getByRole("alert")).toHaveTextContent("unique whole hours");
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("hides settings for disabled modules", () => {
    mount({ ...makerspace, enabled_modules: [] });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
