import type { OfflineRoster, QueuedCheckIn, SyncOutcome } from "./eventCheckInOfflineApi";

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

function isExpired(value: string) {
  const timestamp = Date.parse(value);
  return !Number.isFinite(timestamp) || timestamp <= Date.now();
}

export type OfflineCheckInState = {
  roster: OfflineRoster;
  operations: QueuedCheckIn[];
  conflicts: SyncOutcome[];
  lastSyncedAt: string | null;
};

function requestValue<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function openDatabase() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(KEY_STORE);
      request.result.createObjectStore(BLOB_STORE, { keyPath: "scope" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function keyFor(db: IDBDatabase, scope: string) {
  const read = db.transaction(KEY_STORE).objectStore(KEY_STORE).get(scope);
  const existing = await requestValue(read) as CryptoKey | undefined;
  if (existing) return existing;
  const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  const transaction = db.transaction(KEY_STORE, "readwrite");
  transaction.objectStore(KEY_STORE).put(key, scope);
  await transactionDone(transaction);
  return key;
}

function transactionDone(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

async function write(scope: string, state: OfflineCheckInState) {
  const db = await openDatabase();
  try {
    const key = await keyFor(db, scope);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const cleartext = new TextEncoder().encode(JSON.stringify(state));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, cleartext);
    const transaction = db.transaction(BLOB_STORE, "readwrite");
    transaction.objectStore(BLOB_STORE).put({
      scope, expiresAt: state.roster.expires_at, iv: iv.buffer, ciphertext,
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
    const cleartext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: new Uint8Array(blob.iv) }, key, blob.ciphertext,
    );
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
    const transaction = db.transaction([KEY_STORE, BLOB_STORE], "readwrite");
    transaction.objectStore(KEY_STORE).delete(scope);
    transaction.objectStore(BLOB_STORE).delete(scope);
    await transactionDone(transaction);
  } finally { db.close(); }
}

export async function wipeOfflineScopes(prefix: string) {
  const db = await openDatabase();
  try {
    const blobs = await requestValue(
      db.transaction(BLOB_STORE).objectStore(BLOB_STORE).getAll(),
    ) as StoredBlob[];
    const matching = blobs.filter((blob) => blob.scope.startsWith(prefix));
    const transaction = db.transaction([KEY_STORE, BLOB_STORE], "readwrite");
    for (const blob of matching) {
      transaction.objectStore(KEY_STORE).delete(blob.scope);
      transaction.objectStore(BLOB_STORE).delete(blob.scope);
    }
    await transactionDone(transaction);
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
    const transaction = db.transaction([KEY_STORE, BLOB_STORE], "readwrite");
    for (const blob of expired) {
      transaction.objectStore(KEY_STORE).delete(blob.scope);
      transaction.objectStore(BLOB_STORE).delete(blob.scope);
    }
    await transactionDone(transaction);
  } finally { db.close(); }
}
