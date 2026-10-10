// Crypto/IDB mechanics shared by the legacy event adapter and kiosk queue.
export type Ciphertext = { iv: ArrayBuffer; ciphertext: ArrayBuffer };
export type StoreDefinition = { name: string; keyPath?: string };

export function requestValue<T>(request: IDBRequest<T>) {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function transactionDone(transaction: IDBTransaction) {
  return new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error("Storage transaction aborted."));
  });
}

export function openEncryptedDatabase(name: string, version: number, stores: StoreDefinition[]) {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(name, version);
    request.onupgradeneeded = () => {
      for (const store of stores) {
        if (!request.result.objectStoreNames.contains(store.name)) {
          request.result.createObjectStore(store.name, store.keyPath ? { keyPath: store.keyPath } : undefined);
        }
      }
    };
    request.onsuccess = () => {
      request.result.onversionchange = () => request.result.close();
      resolve(request.result);
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Close older tabs to enable offline storage."));
  });
}

export async function readKey(db: IDBDatabase, scope: string): Promise<CryptoKey | undefined> {
  return requestValue(db.transaction("keys").objectStore("keys").get(scope));
}

export async function keyFor(db: IDBDatabase, scope: string) {
  const existing = await readKey(db, scope);
  if (existing) return existing;
  const candidate = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  // Recheck inside one write transaction: concurrent callers must share ONE key.
  const transaction = db.transaction("keys", "readwrite");
  const done = transactionDone(transaction);
  const store = transaction.objectStore("keys");
  const request = store.get(scope);
  let selected = candidate;
  request.onsuccess = () => {
    if (request.result) selected = request.result as CryptoKey;
    else store.put(candidate, scope);
  };
  await done;
  return selected;
}

export async function encryptBytes(key: CryptoKey, bytes: ArrayBuffer, aad?: string): Promise<Ciphertext> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  return { iv: iv.buffer, ciphertext: await crypto.subtle.encrypt({
    name: "AES-GCM", iv, ...(aad ? { additionalData: new TextEncoder().encode(aad) } : {}),
  }, key, bytes) };
}

export function decryptBytes(key: CryptoKey, value: Ciphertext, aad?: string) {
  return crypto.subtle.decrypt({ name: "AES-GCM", iv: new Uint8Array(value.iv),
    ...(aad ? { additionalData: new TextEncoder().encode(aad) } : {}),
  }, key, value.ciphertext);
}

export function expired(value: string, now = Date.now()) {
  const timestamp = Date.parse(value);
  return !Number.isFinite(timestamp) || timestamp <= now;
}

// Deletion and key destruction share a transaction, including orphaned keys.
export async function deleteScopes(db: IDBDatabase, stores: string[], scopes: string[]) {
  const transaction = db.transaction(["keys", ...stores], "readwrite");
  const done = transactionDone(transaction);
  const matching = new Set(scopes);
  for (const scope of matching) transaction.objectStore("keys").delete(scope);
  for (const name of stores) {
    const store = transaction.objectStore(name);
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      if (matching.has((cursor.value as { scope: string }).scope)) cursor.delete();
      cursor.continue();
    };
  }
  await done;
}
