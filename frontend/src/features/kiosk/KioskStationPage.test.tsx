import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./kioskApi";
import { KioskStationPage } from "./KioskStationPage";

vi.mock("./kioskApi", () => ({
  startKioskSession: vi.fn(),
  endKioskSession: vi.fn(),
  takeOperatorLease: vi.fn(),
  runOnlineCommand: vi.fn(),
}));

const bootstrap: api.KioskBootstrap = {
  station: { id: 3, name: "Front desk", kind: "scanner" },
  makerspace: { id: 1, slug: "space", name: "Space" },
  session_expires_at: "2026-10-09T12:00:00Z",
  permitted_operations: ["resolve_qr"],
};

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/m/:slug/kiosk/:stationToken" element={<KioskStationPage />} />
  </Routes></MemoryRouter>);
}

describe("KioskStationPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("unlocks with the route slug, requires an operator lease, then resolves a QR", async () => {
    vi.mocked(api.startKioskSession).mockResolvedValue(bootstrap);
    vi.mocked(api.takeOperatorLease).mockResolvedValue({
      lease_token: "lease", lease_id: "l", expires_at: "x",
      allowed_actions: ["view_inventory"], permitted_operations: ["resolve_qr"],
    });
    vi.mocked(api.runOnlineCommand).mockResolvedValue({ kind: "resolve_qr", result: { target: { name: "Drill" } } });
    renderAt("/m/space/kiosk/tok");

    fireEvent.change(screen.getByLabelText("Station PIN"), { target: { value: "12345678" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock station" }));
    await screen.findByRole("heading", { name: "Front desk" });
    expect(api.startKioskSession).toHaveBeenCalledWith("tok", "12345678", "space");
    expect(screen.queryByLabelText("Scan or type a QR code")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Start operator shift" }));
    fireEvent.change(await screen.findByLabelText("Scan or type a QR code"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    await screen.findByText("Drill");
    expect(api.runOnlineCommand).toHaveBeenCalledWith("tok", "lease", "resolve_qr", { payload: "abc" });

    fireEvent.click(screen.getByRole("button", { name: "Lock station" }));
    await waitFor(() => expect(screen.getByLabelText("Station PIN")).toBeTruthy());
    expect(api.endKioskSession).toHaveBeenCalledWith("tok");
  });

  it("shows a uniform refusal when the PIN is rejected", async () => {
    vi.mocked(api.startKioskSession).mockRejectedValue(new Error("403"));
    renderAt("/m/space/kiosk/tok");
    fireEvent.change(screen.getByLabelText("Station PIN"), { target: { value: "00000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock station" }));
    expect((await screen.findByRole("alert")).textContent).toContain("invalid");
  });
});
