import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadWorkPackage, takeOperatorLease } from "./kioskApi";
import { enqueueCommand, saveWorkPackage } from "./offlineQueueStore";
import { normalizeEvidence } from "./offlineEvidence";
import { captureCorrection, loadCorrectiveWork } from "./replayCorrectionCapture";
import { session, lease, work } from "./offlineTestFixtures";
import { failedReplay } from "./recoveryTestFixtures";
import type { OfflineQueue } from "./offlineQueueTypes";

vi.mock("./kioskApi", () => ({ loadWorkPackage: vi.fn(), takeOperatorLease: vi.fn() }));
vi.mock("./offlineQueueStore", () => ({ enqueueCommand: vi.fn(), saveWorkPackage: vi.fn() }));
vi.mock("./offlineEvidence", () => ({ normalizeEvidence: vi.fn() }));
const queue: OfflineQueue = { version: 1, scope: "new-shift", token: "token", apiBase: "api", session, lease,
  works: [{ id: "work-id", aggregateId: "fresh-aggregate", work }], commands: [] };

describe("corrective handover capture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(takeOperatorLease).mockResolvedValue(lease);
    vi.mocked(loadWorkPackage).mockResolvedValue(work);
    vi.mocked(saveWorkPackage).mockResolvedValue(queue);
    vi.mocked(enqueueCommand).mockResolvedValue(queue);
  });
  it("takes a fresh lease and loads authoritative work instead of recovering the old payload", async () => {
    await loadCorrectiveWork("token", session, failedReplay);
    expect(takeOperatorLease).toHaveBeenCalledWith("token");
    expect(loadWorkPackage).toHaveBeenCalledWith("token", lease.lease_token, "reviewed_request", 7);
    await expect(loadCorrectiveWork("token", { ...session, makerspace: { ...session.makerspace, id: 99 } }, failedReplay)).rejects.toThrow("makerspace");
  });
  it("persists fresh identity, normalized photo and recovery link together", async () => {
    const file = new File(["photo"], "capture.jpg", { type: "image/jpeg" });
    const photo = new Blob(["normalized"], { type: "image/jpeg" });
    vi.mocked(normalizeEvidence).mockResolvedValue(photo);
    await captureCorrection(queue, failedReplay, { box: "", remark: "New photo", assetQrs: "new-qr\nsecond-qr", photo: file });
    const args = vi.mocked(enqueueCommand).mock.calls[0];
    expect(args[0]).toBe("new-shift");
    expect(args[2].aggregate_id).not.toBe(failedReplay.aggregate_id);
    expect(args[2].payload).toMatchObject({ request_id: 7, asset_qr_payloads: ["new-qr", "second-qr"] });
    expect(args[3]).toBe(photo); expect(args[4]).toBe(failedReplay.id);
  });
  it("does not persist a correction when normalization fails", async () => {
    vi.mocked(normalizeEvidence).mockRejectedValue(new Error("bad photo"));
    await expect(captureCorrection(queue, failedReplay, { box: "", remark: "", assetQrs: "", photo: new File([""], "bad.jpg") })).rejects.toThrow("bad photo");
    expect(enqueueCommand).not.toHaveBeenCalled();
  });
});
