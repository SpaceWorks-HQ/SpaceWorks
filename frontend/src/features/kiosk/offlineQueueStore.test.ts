// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installMemoryIndexedDb } from "../../test/memoryIndexedDb";
import { requestValue, transactionDone } from "../../lib/encryptedIndexedDb";
import { openQueueDb, aad } from "./offlineQueueDb";
import { saveWorkPackage, enqueueCommand, loadQueue, wipeQueue, listQueues, readEvidence } from "./offlineQueueStore";
import { MAX_EVIDENCE_BYTES } from "./offlineQueueTypes";
import { session, lease, work, draft } from "./offlineTestFixtures";
import type { ReplayEnvelope } from "./kioskReplayApi";

beforeEach(() => { installMemoryIndexedDb(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const save = () => saveWorkPackage("station-token", "/api/v1", session, lease, work);

describe("kiosk encrypted queue", () => {
  it("stores private work, envelopes, lease and image only as authenticated ciphertext", async () => {
    const queue = await save();
    const image = new Blob(["PRIVATE-IMAGE"], { type: "image/jpeg" });
    const issue: ReplayEnvelope = { ...draft(), kind: "reviewed_issue", payload: { request_id: 7, remark: "PRIVATE-REMARK" },
      evidence: { evidence_type: "issue", content_type: image.type, size_bytes: image.size } };
    const saved = await enqueueCommand(queue.scope, queue.works[0].id, issue, image);
    const db = await openQueueDb();
    const row = await requestValue(db.transaction("records").objectStore("records").get(queue.scope));
    const photos = await requestValue(db.transaction("evidence").objectStore("evidence").getAll());
    expect(Object.keys(row).sort()).toEqual(["bytes", "ciphertext", "expiresAt", "id", "iv", "scope"]);
    expect(JSON.stringify([row, photos])).not.toMatch(/PRIVATE|SENSITIVE|station-token|remark|request_id/);
    expect(new TextDecoder().decode(await readEvidence(queue.scope, saved.commands[0].evidenceRecordId!))).toBe("PRIVATE-IMAGE");
    expect(aad(queue.scope, "queue", "id")).not.toBe(aad(queue.scope, "evidence", "id"));
    db.close();
  });

  it("atomically appends concurrent captures, retaining sequence and predecessor IDs", async () => {
    const queue = await save(); const a = draft(); const b = draft();
    await Promise.all([enqueueCommand(queue.scope, queue.works[0].id, a), enqueueCommand(queue.scope, queue.works[0].id, b)]);
    const commands = (await loadQueue(queue.scope))!.commands;
    expect(commands.map((cmd) => cmd.envelope.sequence)).toEqual([1, 2]);
    expect(commands[1].envelope.predecessor_client_id).toBe(a.client_command_id);
    expect(commands[1].envelope.aggregate_id).toBe(commands[0].envelope.aggregate_id);
    await expect(enqueueCommand(queue.scope, queue.works[0].id, draft(999))).rejects.toThrow("loaded handover");
    await expect(save()).rejects.toThrow("Acknowledge");
  });

  it("enforces the 50-command cap without dropping an earlier capture", async () => {
    const queue = await save();
    for (let i = 0; i < 50; i += 1) await enqueueCommand(queue.scope, queue.works[0].id, draft());
    await expect(enqueueCommand(queue.scope, queue.works[0].id, draft())).rejects.toThrow("50");
    expect((await loadQueue(queue.scope))?.commands).toHaveLength(50);
  });

  it("blocks over-budget evidence before either command or photo commits", async () => {
    const queue = await save();
    const db = await openQueueDb();
    const tx = db.transaction("evidence", "readwrite"); const done = transactionDone(tx);
    tx.objectStore("evidence").put({ id: "other-image", scope: queue.scope, bytes: MAX_EVIDENCE_BYTES,
      expiresAt: "2999-01-01T00:00:00Z", iv: new ArrayBuffer(12), ciphertext: new ArrayBuffer(16) });
    await done; db.close();
    const image = new Blob(["image"], { type: "image/jpeg" });
    const issue: ReplayEnvelope = { ...draft(), kind: "reviewed_issue", payload: { request_id: 7 },
      evidence: { evidence_type: "issue", content_type: image.type, size_bytes: image.size } };
    await expect(enqueueCommand(queue.scope, queue.works[0].id, issue, image)).rejects.toThrow("100 MiB");
    expect((await loadQueue(queue.scope))!.commands).toEqual([]);
  });

  it("expires at advertised command age, wipes keys/images, and cannot queue fresh work", async () => {
    const queue = await save();
    await enqueueCommand(queue.scope, queue.works[0].id, draft());
    const now = Date.now(); vi.spyOn(Date, "now").mockReturnValue(now + 901_000);
    expect(await loadQueue(queue.scope)).toBeNull();
    expect(await listQueues()).toEqual([]);
    const db = await openQueueDb();
    expect(await requestValue(db.transaction("keys").objectStore("keys").getAllKeys())).toEqual([]);
    expect(await requestValue(db.transaction("evidence").objectStore("evidence").getAll())).toEqual([]);
    db.close(); vi.restoreAllMocks();
    await expect(enqueueCommand(queue.scope, queue.works[0].id, draft())).rejects.toThrow("Reconnect");
  });

  it("rejects ciphertext substitution across scopes and metadata tampering", async () => {
    const a = await save();
    const b = await saveWorkPackage("station-token", "/api/v1", session, { ...lease, lease_id: "other-lease" }, work);
    const db = await openQueueDb();
    const row = await requestValue(db.transaction("records").objectStore("records").get(a.scope));
    const tx = db.transaction("records", "readwrite"); const done = transactionDone(tx);
    tx.objectStore("records").put({ ...row, scope: b.scope, id: "other-lease" });
    await done; db.close();
    await expect(loadQueue(b.scope)).rejects.toThrow();
    await wipeQueue(a.scope); await wipeQueue(b.scope);
    expect(await listQueues()).toEqual([]);
  });

  it("refuses missing scope metadata and unavailable Web Locks without plaintext fallback", async () => {
    await expect(saveWorkPackage("token", "/api/v1", session, { ...lease, actor_id: undefined }, work)).rejects.toThrow("offline-capable");
    vi.stubGlobal("navigator", {});
    await expect(save()).rejects.toThrow("Continue online");
  });
});
