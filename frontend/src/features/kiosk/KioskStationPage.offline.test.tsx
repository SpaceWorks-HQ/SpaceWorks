import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { KioskStationPage } from "./KioskStationPage";
import { session, lease, work } from "./offlineTestFixtures";
import type { OfflineQueue } from "./offlineQueueTypes";
import { useKioskQueue } from "./useKioskQueue";
import { endKioskSession } from "./kioskApi";

vi.mock("./useKioskQueue", () => ({ useKioskQueue: vi.fn(), registerKioskSync: vi.fn() }));
vi.mock("./kioskApi", () => ({ endKioskSession: vi.fn().mockResolvedValue(undefined) }));
const reset = vi.fn().mockResolvedValue(undefined);
const hook = { queue: null as OfflineQueue | null, setQueue: vi.fn(), online: false,
  storageError: null, restored: false, save: vi.fn(), refresh: vi.fn(), retry: vi.fn(), reset };
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useKioskQueue).mockReturnValue({ ...hook });
});
afterEach(() => { vi.unstubAllGlobals(); });
function show() {
  return render(<MemoryRouter initialEntries={["/m/space/kiosk/token"]}><Routes>
    <Route path="/m/:slug/kiosk/:stationToken" element={<KioskStationPage />} />
  </Routes></MemoryRouter>);
}
it("cold offline shell refuses unlock, search and capture", () => {
  show();
  expect(screen.getByText("Reconnect to unlock and load this handover")).toBeTruthy();
  expect(screen.queryByLabelText("Station PIN")).toBeNull();
  expect(screen.queryByLabelText("Request number")).toBeNull();
  expect(screen.queryByRole("button", { name: "Queue handover" })).toBeNull();
});
it("restores only the selected encrypted handover and presents pending work as Queued", async () => {
  const queue: OfflineQueue = { version: 1, scope: "scope", token: "token", apiBase: "/api/v1", session, lease,
    works: [{ id: "work", aggregateId: "aggregate", work }], commands: [{
      envelope: { kind: "assign_box", version: 1, client_command_id: "command", aggregate_id: "aggregate", sequence: 1,
        client_created_at: new Date().toISOString(), payload: { request_id: 7, box_code: "box" } },
      workPackageId: "work", evidenceRecordId: null, status: "queued", attempts: 0, nextRetryAt: 0,
      lastFailure: null, result: null, uploaded: false,
    }] };
  vi.mocked(useKioskQueue).mockReturnValue({ ...hook, queue, restored: true });
  show();
  expect(screen.getByText(/Sequence 1.*Queued/)).toBeTruthy();
  expect(screen.queryByLabelText("Request number")).toBeNull();
  expect(screen.queryByRole("button", { name: "Look up" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Lock station" }));
  expect(reset).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Discard local work and lock" }));
  await screen.findByText(/Locking clears/);
  expect(reset).toHaveBeenCalledTimes(1);
  // The server channel is explicitly ended only after local key/data destruction.
  await vi.waitFor(() => expect(endKioskSession).toHaveBeenCalledWith("token"));
});
