import {
  openEncryptedDatabase, requestValue, transactionDone, readKey,
  encryptBytes, decryptBytes, deleteScopes, expired,
  type Ciphertext,
} from "../../lib/encryptedIndexedDb";
import { KIOSK_DB, queueDeadline, type OfflineQueue } from "./offlineQueueTypes";

export type StoredRecord = Ciphertext & { scope: string; id: string; expiresAt: string; bytes: number };
export const openQueueDb = () => openEncryptedDatabase(KIOSK_DB, 1, [
  { name: "keys" }, { name: "records", keyPath: "scope" }, { name: "evidence", keyPath: "id" },
]);
export const aad = (scope: string, kind: string, id: string) => JSON.stringify([KIOSK_DB, 1, scope, kind, id]);

export async function withQueueLock<T>(task: () => Promise<T>): Promise<T> {
  if (!navigator.locks) throw new Error("Offline storage is unavailable. Continue online on this browser.");
  return navigator.locks.request(`${KIOSK_DB}:storage`, task);
}

export function withReplayLock<T>(scope: string, task: () => Promise<T>): Promise<T> {
  if (!navigator.locks) throw new Error("Offline replay is unavailable on this browser.");
  return navigator.locks.request(`${KIOSK_DB}:replay:${scope}`, task);
}

export async function decodeQueue(db: IDBDatabase, row: StoredRecord): Promise<OfflineQueue | null> {
  const key = await readKey(db, row.scope);
  if (!key) return null;
  const bytes = await decryptBytes(key, row, aad(row.scope, "queue", row.id));
  const state = JSON.parse(new TextDecoder().decode(bytes)) as OfflineQueue;
  if (state.version !== 1 || state.scope !== row.scope || row.id !== state.lease.lease_id
      || row.expiresAt !== queueDeadline(state)) throw new Error("Offline queue integrity check failed.");
  return state;
}

export async function readQueue(db: IDBDatabase, scope: string) {
  const row = await requestValue(db.transaction("records").objectStore("records").get(scope)) as StoredRecord | undefined;
  if (!row) return null;
  if (expired(row.expiresAt)) {
    await deleteScopes(db, ["records", "evidence"], [scope]);
    return null;
  }
  const state = await decodeQueue(db, row);
  if (state && expired(queueDeadline(state))) return null;
  return state;
}

export async function encodeQueue(key: CryptoKey, state: OfflineQueue): Promise<StoredRecord> {
  const encrypted = await encryptBytes(key, new TextEncoder().encode(JSON.stringify(state)).buffer,
    aad(state.scope, "queue", state.lease.lease_id));
  return { ...encrypted, scope: state.scope, id: state.lease.lease_id,
    expiresAt: queueDeadline(state), bytes: encrypted.ciphertext.byteLength };
}

export async function writeQueue(db: IDBDatabase, row: StoredRecord, evidence?: StoredRecord) {
  const transaction = db.transaction(["records", "evidence"], "readwrite");
  const done = transactionDone(transaction);
  transaction.objectStore("records").put(row);
  if (evidence) transaction.objectStore("evidence").add(evidence);
  await done;
}
