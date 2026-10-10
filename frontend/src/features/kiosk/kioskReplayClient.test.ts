// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installMemoryIndexedDb } from "../../test/memoryIndexedDb";
import { StructuredApiError } from "../../lib/api/errors";
import { prepareReplay, executeReplay } from "./kioskReplayApi";
import { saveWorkPackage, enqueueCommand, loadQueue, updateCommand } from "./offlineQueueStore";
import { replayQueue, uploadReplayEvidence } from "./kioskReplayClient";
import { classifyReplayError, retryDelay } from "./replayPolicy";
import { session, lease, work, draft, replayResult } from "./offlineTestFixtures";
import type { ReplayEnvelope } from "./kioskReplayApi";

vi.mock("./kioskReplayApi", () => ({ prepareReplay: vi.fn(), executeReplay: vi.fn() }));
beforeEach(() => {
  installMemoryIndexedDb(); vi.clearAllMocks();
  vi.mocked(prepareReplay).mockImplementation(async (_token, _lease, envelope) => replayResult(envelope, "prepared"));
  vi.mocked(executeReplay).mockImplementation(async (_token, _lease, envelope) => replayResult(envelope));
});
afterEach(() => { vi.unstubAllGlobals(); });
async function queued() {
  const queue = await saveWorkPackage("token", "/api/v1", session, lease, work);
  return enqueueCommand(queue.scope, queue.works[0].id, draft());
}

describe("encrypted replay state machine", () => {
  it("recovers uncertain delivery with the SAME UUID/envelope; duplicate success skips execute", async () => {
    const queue = await queued();
    vi.mocked(executeReplay).mockRejectedValueOnce(new TypeError("network lost after server committed"));
    await replayQueue(queue.scope);
    let command = (await loadQueue(queue.scope))!.commands[0];
    expect(command.status).toBe("queued"); expect(command.lastFailure).toBe("network_unavailable");
    expect(command.nextRetryAt).toBeGreaterThan(Date.now());
    await updateCommand(queue.scope, command.envelope.client_command_id, { nextRetryAt: 0 });
    vi.mocked(prepareReplay).mockResolvedValueOnce(replayResult(command.envelope));
    await replayQueue(queue.scope);
    command = (await loadQueue(queue.scope))!.commands[0];
    expect(command.status).toBe("succeeded");
    expect(executeReplay).toHaveBeenCalledTimes(1);
    expect(vi.mocked(prepareReplay).mock.calls[0][2]).toEqual(vi.mocked(prepareReplay).mock.calls[1][2]);
  });

  it("blocks a failed aggregate's successor while independent handovers continue", async () => {
    let queue = await queued(); const first = queue.commands[0];
    queue = await enqueueCommand(queue.scope, queue.works[0].id, draft());
    queue = await saveWorkPackage("token", "/api/v1", session, lease, { ...work, id: 8 });
    queue = await enqueueCommand(queue.scope, queue.works[1].id, draft(8));
    vi.mocked(executeReplay).mockImplementation(async (_token, _lease, envelope) => {
      if (envelope.aggregate_id === first.envelope.aggregate_id) throw new StructuredApiError(409, { code: "request_state_changed" });
      return replayResult(envelope);
    });
    await replayQueue(queue.scope);
    expect((await loadQueue(queue.scope))!.commands.map((cmd) => cmd.status)).toEqual(["failed", "queued", "succeeded"]);
    expect(executeReplay).toHaveBeenCalledTimes(2);
  });

  it("waits for claim contention without running its successor, then reuses stable server IDs", async () => {
    const queue = await queued();
    await enqueueCommand(queue.scope, queue.works[0].id, draft());
    vi.mocked(prepareReplay).mockRejectedValueOnce(new StructuredApiError(409, { code: "claim_in_progress" }));
    await replayQueue(queue.scope);
    expect(executeReplay).not.toHaveBeenCalled();
    const command = (await loadQueue(queue.scope))!.commands[0];
    await updateCommand(queue.scope, command.envelope.client_command_id, { nextRetryAt: 0 });
    await replayQueue(queue.scope);
    expect((await loadQueue(queue.scope))!.commands.map((cmd) => cmd.status)).toEqual(["succeeded", "succeeded"]);
  });

  it("resumes persisted preparing/uploading/executing states after a context closes", async () => {
    const queue = await queued();
    await updateCommand(queue.scope, queue.commands[0].envelope.client_command_id, { status: "executing" });
    await Promise.all([replayQueue(queue.scope), replayQueue(queue.scope)]);
    expect(executeReplay).toHaveBeenCalledTimes(1);
    expect((await loadQueue(queue.scope))!.commands[0].status).toBe("succeeded");
  });

  it("wipes revoked authority but retains borrower presence/membership/waiver failures", async () => {
    const queue = await queued();
    vi.mocked(executeReplay).mockRejectedValueOnce(new StructuredApiError(403, { code: "presence_expired" }));
    await replayQueue(queue.scope);
    expect((await loadQueue(queue.scope))!.commands[0].status).toBe("failed");
    const other = await saveWorkPackage("token", "/api/v1", session, { ...lease, lease_id: "other" }, work);
    await enqueueCommand(other.scope, other.works[0].id, draft());
    vi.mocked(prepareReplay).mockRejectedValueOnce(new StructuredApiError(403, { code: "station_revoked" }));
    await replayQueue(other.scope);
    expect(await loadQueue(other.scope)).toBeNull();
    for (const code of ["membership_required", "waiver_required"]) {
      expect(classifyReplayError(new StructuredApiError(403, { code })).action).toBe("fail");
    }
    for (const status of [401, 403, 410]) expect(classifyReplayError(new StructuredApiError(status, {})).action).toBe("wipe");
  });

  it("uploads decrypted evidence directly and keeps it out of the envelope and result", async () => {
    let queue = await saveWorkPackage("token", "/api/v1", session, lease, work);
    const image = new Blob(["photo"], { type: "image/jpeg" });
    const envelope: ReplayEnvelope = { ...draft(), kind: "reviewed_issue", payload: { request_id: 7 },
      evidence: { evidence_type: "issue", content_type: "image/jpeg", size_bytes: image.size } };
    queue = await enqueueCommand(queue.scope, queue.works[0].id, envelope, image);
    const command = queue.commands[0];
    const presign = { evidence_id: 42, object_key: "final-id", upload_url: "https://storage/staging", fields: { key: "staging/id" } };
    vi.mocked(prepareReplay).mockResolvedValue({ ...replayResult(command.envelope, "prepared"), evidence_id: 42, upload: presign });
    const fetcher = vi.fn().mockResolvedValue({ ok: true }); vi.stubGlobal("fetch", fetcher);
    await replayQueue(queue.scope);
    expect(fetcher.mock.calls[0][0]).toBe(presign.upload_url);
    const options = fetcher.mock.calls[0][1];
    expect(options.credentials).toBe("omit"); expect(options.cache).toBe("no-store");
    expect(await options.body.get("file").text()).toBe("photo");
    expect(vi.mocked(executeReplay).mock.calls[0][2]).toEqual(command.envelope);
    expect(JSON.stringify((await loadQueue(queue.scope))!.commands)).not.toContain("https://storage");
  });

  it("supports PUT headers and treats storage 403 as a retryable expired presign", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 403 }); vi.stubGlobal("fetch", fetcher);
    await expect(uploadReplayEvidence({ evidence_id: 1, object_key: "id", upload_url: "https://storage", method: "PUT",
      fields: {}, headers: { "Content-Type": "image/jpeg" } }, new Blob(["photo"]))).rejects.toMatchObject({ status: 503 });
    expect(fetcher.mock.calls[0][1].method).toBe("PUT");
    expect(fetcher.mock.calls[0][1].headers).toEqual({ "Content-Type": "image/jpeg" });
    expect(retryDelay(100, () => 0.5)).toBe(60_000);
    expect(retryDelay(1, () => 0)).toBeLessThan(retryDelay(1, () => 1));
  });
});
