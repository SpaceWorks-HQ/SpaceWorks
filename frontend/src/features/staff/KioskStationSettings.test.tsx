import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { staffRequest } from "../../lib/api";
import { KioskStationSettings } from "./KioskStationSettings";
import type { Makerspace } from "./StaffPanels";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));

describe("KioskStationSettings", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates a Station and shows its PIN once from the mutation result", async () => {
    vi.mocked(staffRequest).mockImplementation(async (_path: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        return { id: 9, name: "Desk", kind: "handover", enabled: true, public_token: "t", version: 1, station_url: "http://x/m/s/kiosk/t", pin: "12345678" };
      }
      return [] as never;
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><KioskStationSettings makerspace={{ id: 4 } as Makerspace} /></QueryClientProvider>);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Desk" } });
    fireEvent.click(screen.getByRole("button", { name: "Create station" }));
    expect((await screen.findByRole("status")).textContent).toContain("12345678");
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/4/kiosk-stations/", {
      method: "POST", body: JSON.stringify({ name: "Desk", kind: "handover" }),
    });
  });
});
