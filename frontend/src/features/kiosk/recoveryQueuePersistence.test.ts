// @vitest-environment node
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installMemoryIndexedDb } from "../../test/memoryIndexedDb";
import { requestValue } from "../../lib/encryptedIndexedDb";
import { openQueueDb } from "./offlineQueueDb";
import { enqueueCommand, loadQueue, saveWorkPackage } from "./offlineQueueStore";
import { session, lease, work, draft } from "./offlineTestFixtures";
import { failedReplay } from "./recoveryTestFixtures";

beforeEach(() => installMemoryIndexedDb());
afterEach(() => vi.unstubAllGlobals());
it("retains the recovery link inside encrypted queue state across reload", async () => {
  const queue = await saveWorkPackage("token", "/api/v1", session, lease, work);
  await enqueueCommand(queue.scope, queue.works[0].id, draft(), undefined, failedReplay.id);
  expect((await loadQueue(queue.scope))?.commands[0].recoveryReplayId).toBe(failedReplay.id);
  const db = await openQueueDb();
  try {
    const stored = await requestValue(db.transaction("records").objectStore("records").getAll());
    expect(JSON.stringify(stored)).not.toContain(failedReplay.id);
    expect(JSON.stringify(stored)).not.toContain("recoveryReplayId");
  } finally { db.close(); }
});
