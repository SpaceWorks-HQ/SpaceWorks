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
  loadWorkPackage: vi.fn(),
  prepareEvidence: vi.fn(),
}));

// These tests pin 9b online behavior; offline storage/reachability have separate
// real-storage, presentation and production-browser coverage.
vi.mock("./useKioskQueue", () => ({ useKioskQueue: () => ({
  queue: null, setQueue: vi.fn(), online: true, storageError: null, restored: false,
  save: vi.fn(), retry: vi.fn(), reset: vi.fn().mockResolvedValue(undefined),
}) }));

const bootstrap: api.KioskBootstrap = {
  station: { id: 3, name: "Front desk", kind: "scanner" },
  makerspace: { id: 1, slug: "space", name: "Space" },
  session_expires_at: "2999-01-01T00:00:00Z",
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
      lease_token: "lease", lease_id: "l", expires_at: "2999-01-01T00:00:00Z",
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

  it("loads a reviewed request on a handover Station and assigns its box through the lease", async () => {
    vi.mocked(api.startKioskSession).mockResolvedValue({ ...bootstrap, station: { id: 4, name: "Desk", kind: "handover" } });
    vi.mocked(api.takeOperatorLease).mockResolvedValue({
      lease_token: "lease", lease_id: "l", expires_at: "2999-01-01T00:00:00Z",
      allowed_actions: ["assign_box"], permitted_operations: ["resolve_qr", "assign_box"],
    });
    const work: api.KioskWorkPackage = {
      kind: "reviewed_request", id: 7, status: "accepted", display_label: "Request #7", person_display: "Ada",
      box: null, lines: [{ item_id: 1, label: "Drill", quantity: 1, returned: 0 }], return_resolutions: [],
      expires_at: "x", command_age_limit_seconds: 900, evidence_max_bytes: 1,
    };
    vi.mocked(api.loadWorkPackage).mockResolvedValue(work);
    vi.mocked(api.runOnlineCommand).mockResolvedValue({ kind: "assign_box", result: {} });
    renderAt("/m/space/kiosk/tok");
    fireEvent.change(screen.getByLabelText("Station PIN"), { target: { value: "12345678" } });
    fireEvent.click(screen.getByRole("button", { name: "Unlock station" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start operator shift" }));
    fireEvent.change(await screen.findByLabelText("Request number"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Load request" }));
    expect(await screen.findByText(/Drill/)).toBeTruthy();
    expect(api.loadWorkPackage).toHaveBeenCalledWith("tok", "lease", "reviewed_request", 7);
    fireEvent.change(screen.getByLabelText("Box code"), { target: { value: "BOX1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign box" }));
    await screen.findByText("Box assigned.");
    expect(api.runOnlineCommand).toHaveBeenCalledWith("tok", "lease", "assign_box", { request_id: 7, box_code: "BOX1" });
  });
});
