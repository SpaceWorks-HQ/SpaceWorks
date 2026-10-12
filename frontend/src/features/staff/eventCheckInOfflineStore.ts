import type { OfflineRoster, QueuedCheckIn, SyncOutcome } from "./eventCheckInOfflineApi";
import { openEncryptedDatabase, requestValue, transactionDone, keyFor, encryptBytes, decryptBytes, expired as isExpired, deleteScopes } from "../../lib/encryptedIndexedDb";

const DB_NAME = "spaceworks-event-checkin-v1";
const DB_VERSION = 1;
const KEY_STORE = "keys";
const BLOB_STORE = "blobs";

type StoredBlob = {
  scope: string;
  expiresAt: string;
  iv: ArrayBuffer;
  ciphertext: ArrayBuffer;
};

export type OfflineCheckInState = {
  roster: OfflineRoster;
  operations: QueuedCheckIn[];
  conflicts: SyncOutcome[];
  lastSyncedAt: string | null;
};

function openDatabase() {
  return openEncryptedDatabase(DB_NAME, DB_VERSION, [
    { name: KEY_STORE }, { name: BLOB_STORE, keyPath: "scope" },
  ]);
}

async function write(scope: string, state: OfflineCheckInState) {
  const db = await openDatabase();
  try {
    const key = await keyFor(db, scope);
    const cleartext = new TextEncoder().encode(JSON.stringify(state));
    const encrypted = await encryptBytes(key, cleartext.buffer);
    const transaction = db.transaction(BLOB_STORE, "readwrite");
    transaction.objectStore(BLOB_STORE).put({
      scope, expiresAt: state.roster.expires_at, ...encrypted,
    } satisfies StoredBlob);
    await transactionDone(transaction);
  } finally { db.close(); }
}

export async function saveOfflineRoster(scope: string, roster: OfflineRoster) {
  const state: OfflineCheckInState = { roster, operations: [], conflicts: [], lastSyncedAt: null };
  await write(scope, state);
  return state;
}

export async function loadOfflineState(scope: string): Promise<OfflineCheckInState | null> {
  const db = await openDatabase();
  try {
    const blob = await requestValue(
      db.transaction(BLOB_STORE).objectStore(BLOB_STORE).get(scope),
    ) as StoredBlob | undefined;
    if (!blob) return null;
    if (isExpired(blob.expiresAt)) {
      db.close();
      await wipeOfflineState(scope);
      return null;
    }
    const key = await requestValue(
      db.transaction(KEY_STORE).objectStore(KEY_STORE).get(scope),
    ) as CryptoKey | undefined;
    if (!key) return null;
    const cleartext = await decryptBytes(key, blob);
    const state = JSON.parse(new TextDecoder().decode(cleartext)) as OfflineCheckInState;
    if (state.roster.expires_at !== blob.expiresAt || isExpired(state.roster.expires_at)) {
      db.close();
      await wipeOfflineState(scope);
      return null;
    }
    return state;
  } finally { if (db.name) db.close(); }
}

export async function queueOfflineCheckIn(scope: string, operation: QueuedCheckIn) {
  const state = await loadOfflineState(scope);
  if (!state) throw new Error("The offline roster expired. Download it again.");
  state.operations.push(operation);
  await write(scope, state);
  return state;
}

export async function applySyncResults(scope: string, outcomes: SyncOutcome[], recordedAt: string) {
  const state = await loadOfflineState(scope);
  if (!state) return null;
  const completed = new Set(outcomes.map((item) => item.operation_id));
  state.operations = state.operations.filter((item) => !completed.has(item.operation_id));
  state.conflicts = outcomes.filter((item) => !["applied", "duplicate_operation"].includes(item.outcome));
  state.lastSyncedAt = recordedAt;
  await write(scope, state);
  return state;
}

export async function wipeOfflineState(scope: string) {
  const db = await openDatabase();
  try {
    await deleteScopes(db, [BLOB_STORE], [scope]);
  } finally { db.close(); }
}

export async function wipeOfflineScopes(prefix: string) {
  const db = await openDatabase();
  try {
    const blobs = await requestValue(
      db.transaction(BLOB_STORE).objectStore(BLOB_STORE).getAll(),
    ) as StoredBlob[];
    const matching = blobs.filter((blob) => blob.scope.startsWith(prefix));
    await deleteScopes(db, [BLOB_STORE], matching.map((blob) => blob.scope));
  } finally { db.close(); }
}

export async function pruneExpiredOfflineStates() {
  const db = await openDatabase();
  try {
    const blobs = await requestValue(
      db.transaction(BLOB_STORE).objectStore(BLOB_STORE).getAll(),
    ) as StoredBlob[];
    const expired = blobs.filter((blob) => isExpired(blob.expiresAt));
    if (!expired.length) return;
    await deleteScopes(db, [BLOB_STORE], expired.map((blob) => blob.scope));
  } finally { db.close(); }
}
