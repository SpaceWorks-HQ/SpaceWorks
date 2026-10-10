// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installMemoryIndexedDb } from "../../test/memoryIndexedDb";
import { openEncryptedDatabase, transactionDone, encryptBytes, requestValue } from "../../lib/encryptedIndexedDb";
import { loadOfflineState, queueOfflineCheckIn, applySyncResults, wipeOfflineScopes, pruneExpiredOfflineStates, saveOfflineRoster } from "./eventCheckInOfflineStore";
import type { OfflineRoster } from "./eventCheckInOfflineApi";

const roster: OfflineRoster = {
  lease_token: "legacy-lease", lease_id: "lease", server_time: "2026-10-10T00:00:00Z",
  issued_at: "2026-10-10T00:00:00Z", expires_at: "2999-01-01T00:00:00Z",
  scan_opens_at: "2026-10-10T00:00:00Z", scan_closes_at: "2999-01-01T00:00:00Z", sync_deadline: "2999-01-01T00:00:00Z",
  event: { id: 1, title: "Event", starts_at: "2026-10-10T00:00:00Z", ends_at: "2999-01-01T00:00:00Z" },
  registrations: [{ registration_id: 1, checkin_token: "private-qr", name: "Person", host_waiver_state: "on_file" }],
};
beforeEach(() => { installMemoryIndexedDb(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("event encrypted storage compatibility", () => {
  it("reads a pre-extraction version-one fixture encrypted without AAD", async () => {
    const db = await openEncryptedDatabase("spaceworks-event-checkin-v1", 1, [
      { name: "keys" }, { name: "blobs", keyPath: "scope" },
    ]);
    const scope = "staff:3:1";
    const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    const state = { roster, operations: [], conflicts: [], lastSyncedAt: null };
    // Exact old blob wire format, generated independently of the shared adapter.
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(JSON.stringify(state)));
    const tx = db.transaction(["keys", "blobs"], "readwrite");
    const done = transactionDone(tx);
    tx.objectStore("keys").put(key, scope);
    tx.objectStore("blobs").put({ scope, expiresAt: roster.expires_at, iv: iv.buffer, ciphertext });
    await done; db.close();
    expect(await loadOfflineState(scope)).toEqual(state);
    const op = { operation_id: "op", checkin_token: "private-qr", reported_occurred_at: "2026-10-10T01:00:00Z" };
    expect((await queueOfflineCheckIn(scope, op)).operations).toEqual([op]);
    const outcome = { operation_id: "op", outcome: "registration_changed" as const };
    const synced = await applySyncResults(scope, [outcome], "2026-10-10T02:00:00Z");
    expect(synced?.operations).toEqual([]);
    expect(synced?.conflicts).toEqual([outcome]);
    expect(synced?.lastSyncedAt).toBe("2026-10-10T02:00:00Z");
  });

  it("preserves prefix wipe and expiry cleanup of keys and blobs", async () => {
    await saveOfflineRoster("staff:3:1", roster);
    await saveOfflineRoster("staff:4:1", roster);
    await saveOfflineRoster("expired", { ...roster, expires_at: "2000-01-01T00:00:00Z" });
    await wipeOfflineScopes("staff:3:"); await pruneExpiredOfflineStates();
    expect(await loadOfflineState("staff:3:1")).toBeNull();
    expect(await loadOfflineState("expired")).toBeNull();
    expect(await loadOfflineState("staff:4:1")).not.toBeNull();
    const db = await openEncryptedDatabase("spaceworks-event-checkin-v1", 1, []);
    expect(await requestValue(db.transaction("keys").objectStore("keys").getAllKeys())).toEqual(["staff:4:1"]);
    db.close();
  });

  it("refuses state whose encrypted expiry disagrees with plaintext pruning metadata", async () => {
    const db = await openEncryptedDatabase("spaceworks-event-checkin-v1", 1, [{ name: "keys" }, { name: "blobs", keyPath: "scope" }]);
    const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    const encrypted = await encryptBytes(key, new TextEncoder().encode(JSON.stringify({ roster })).buffer);
    const tx = db.transaction(["keys", "blobs"], "readwrite"); const done = transactionDone(tx);
    tx.objectStore("keys").put(key, "bad");
    tx.objectStore("blobs").put({ scope: "bad", expiresAt: "2998-01-01T00:00:00Z", ...encrypted });
    await done; db.close();
    expect(await loadOfflineState("bad")).toBeNull();
  });
});
