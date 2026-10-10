import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { failedReplay } from "./recoveryTestFixtures";
import { session, lease, work, draft, replayResult } from "./offlineTestFixtures";
import type { OfflineQueue } from "./offlineQueueTypes";
import { KioskReplayCorrection } from "./KioskReplayCorrection";
import { captureCorrection, loadCorrectiveWork } from "./replayCorrectionCapture";
import { listQueues, loadQueue } from "./offlineQueueStore";
import { replayQueue } from "./kioskReplayClient";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(), staffRequest: vi.fn() }));
vi.mock("./offlineQueueStore", () => ({ listQueues: vi.fn(), loadQueue: vi.fn() }));
vi.mock("./kioskReplayClient", () => ({ replayQueue: vi.fn() }));
vi.mock("./replayCorrectionCapture", () => ({ captureCorrection: vi.fn(), loadCorrectiveWork: vi.fn() }));

const base: OfflineQueue = { version: 1, token: "token", apiBase: "api", scope: "corrective-shift", session, lease,
  works: [{ id: "work-id", aggregateId: "fresh", work }], commands: [] };
const envelope = draft();
const success: OfflineQueue = { ...base, commands: [{ envelope, recoveryReplayId: failedReplay.id,
  workPackageId: "work-id", evidenceRecordId: "photo", status: "succeeded", attempts: 1, nextRetryAt: 0,
  lastFailure: null, result: replayResult(envelope), uploaded: true }] };
const onQueueChange = vi.fn();
function show(online = true) {
  return render(<KioskReplayCorrection id={failedReplay.id} token="token" session={session} online={online} onQueueChange={onQueueChange} />);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(staffRequest).mockResolvedValue(failedReplay);
  vi.mocked(listQueues).mockResolvedValue([]);
  vi.mocked(loadCorrectiveWork).mockResolvedValue(base);
  vi.mocked(captureCorrection).mockResolvedValue(success);
  vi.mocked(loadQueue).mockResolvedValue(success);
  vi.mocked(replayQueue).mockResolvedValue(undefined);
});

it("never obtains work or posts review while offline", () => {
  show(false);
  expect(screen.getByText(/Reconnect to review/)).toBeTruthy();
  expect(staffRequest).not.toHaveBeenCalled();
  expect(loadCorrectiveWork).not.toHaveBeenCalled();
});

it("captures through the queue, then explicitly links only server success", async () => {
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Start corrective shift and load current work" }));
  const submit = await screen.findByRole("button", { name: "Capture fresh correction" });
  fireEvent.change(screen.getByLabelText("New correction photo"), { target: { files: [new File(["photo"], "new.jpg", { type: "image/jpeg" })] } });
  fireEvent.submit(submit.closest("form")!);
  await screen.findByRole("button", { name: "Link successful correction" });
  expect(replayQueue).toHaveBeenCalledWith("corrective-shift");
  expect(onQueueChange).toHaveBeenCalledWith(success);
  expect(vi.mocked(staffRequest).mock.calls.some(([path]) => path.endsWith("resolve/"))).toBe(false);
  vi.mocked(staffRequest).mockResolvedValueOnce({ ...failedReplay, resolution_code: "replaced_online", resolved_by_display: "Operator" });
  fireEvent.click(screen.getByRole("button", { name: "Link successful correction" }));
  await screen.findByText(/Resolved: replaced online/);
  expect(staffRequest).toHaveBeenLastCalledWith(`/admin/kiosk-replays/${failedReplay.id}/resolve/`, {
    method: "POST", body: JSON.stringify({ resolution_code: "replaced_online", replacement_command_id: "server-id" }),
  });
});

it("retains the original unresolved row and queued identity on corrective failure", async () => {
  const failed: OfflineQueue = { ...success, commands: [{ ...success.commands[0], status: "failed",
    result: null, lastFailure: "inventory_unavailable" }] };
  vi.mocked(captureCorrection).mockResolvedValue(failed);
  vi.mocked(loadQueue).mockResolvedValue(failed);
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Start corrective shift and load current work" }));
  fireEvent.submit((await screen.findByRole("button", { name: "Capture fresh correction" })).closest("form")!);
  await screen.findByText(/Correction failed/);
  expect(screen.queryByRole("button", { name: "Link successful correction" })).toBeNull();
  expect(vi.mocked(staffRequest).mock.calls.some(([path]) => path.endsWith("resolve/"))).toBe(false);
});

it("restores a persisted correction and exposes link without executing again", async () => {
  vi.mocked(listQueues).mockResolvedValue([success]);
  show();
  await screen.findByRole("button", { name: "Link successful correction" });
  expect(replayQueue).not.toHaveBeenCalled();
  await waitFor(() => expect(onQueueChange).toHaveBeenCalledWith(success));
});
