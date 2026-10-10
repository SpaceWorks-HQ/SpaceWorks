// Small IDB test double for this suite's get/put/delete/cursor operations. Real
// WebCrypto and structuredClone run in Node; production uses browser IndexedDB.
// This deliberately models transaction completion/rollback, not storage adapters.
import { vi } from "vitest";

type Value = { key: IDBValidKey; value: unknown };
type Data = { keyPath?: string; values: Map<string, Value> };
type Db = { name: string; version: number; stores: Map<string, Data>; tail: Promise<void> };
type Request = { result?: unknown; error?: DOMException; onsuccess?: () => void; onerror?: () => void };
const clone = <T>(value: T): T => value === undefined ? value : structuredClone(value);
const keyString = (key: IDBValidKey) => JSON.stringify(key);

class Transaction {
  oncomplete?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  error: DOMException | null = null;
  pending = 0;
  finished = false;
  private timer?: ReturnType<typeof setTimeout>;
  private stores = new Map<string, Data>();
  private ready: Promise<void>;
  private release!: () => void;
  constructor(private db: Db, private names: string[], private writable: boolean) {
    const previous = db.tail;
    db.tail = new Promise<void>((resolve) => { this.release = resolve; });
    this.ready = previous.then(() => {
      this.stores = new Map(names.map((name) => [name, clone(db.stores.get(name)!)]));
      this.finishLater();
    });
  }
  private finishLater() {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      if (this.finished || this.pending) return;
      this.finished = true;
      if (this.writable) for (const name of this.names) this.db.stores.set(name, this.stores.get(name)!);
      this.oncomplete?.();
      this.release();
    }, 0);
  }
  abort() {
    this.finished = true;
    clearTimeout(this.timer);
    this.onabort?.();
    this.release();
  }
  request(task: () => unknown, reused?: Request): Request {
    const request: Request = reused ?? {};
    this.pending += 1;
    clearTimeout(this.timer);
    void this.ready.then(() => {
      if (this.finished) return;
      try {
        request.result = clone(task());
        request.onsuccess?.();
      } catch (error) {
        this.error = error instanceof DOMException ? error : new DOMException("IDB request failed", "DataError");
        request.error = this.error;
        request.onerror?.();
        this.onerror?.(); this.abort();
      } finally { this.pending -= 1; this.finishLater(); }
    });
    return request;
  }
  objectStore(name: string) {
    const data = () => this.stores.get(name)!;
    const write = (value: unknown, supplied: IDBValidKey | undefined, add = false) => {
      if (!this.writable) throw new DOMException("Readonly", "ReadOnlyError");
      const key = supplied ?? (value as Record<string, IDBValidKey>)[data().keyPath!];
      if (add && data().values.has(keyString(key))) throw new DOMException("Duplicate", "ConstraintError");
      data().values.set(keyString(key), { key, value: clone(value) });
      return key;
    };
    return {
      get: (key: IDBValidKey) => this.request(() => data().values.get(keyString(key))?.value),
      getAll: () => this.request(() => [...data().values.values()].map((item) => item.value)),
      getAllKeys: () => this.request(() => [...data().values.values()].map((item) => item.key)),
      put: (value: unknown, key?: IDBValidKey) => this.request(() => write(value, key)),
      add: (value: unknown, key?: IDBValidKey) => this.request(() => write(value, key, true)),
      delete: (key: IDBValidKey) => this.request(() => { data().values.delete(keyString(key)); }),
      openCursor: () => {
        let items: Value[] | undefined;
        let position = 0;
        const request: Request = {};
        const step = () => {
          items ??= [...data().values.values()];
          const item = items[position];
          if (!item) return null;
          // Cursor is not cloneable; create it on success after cloning the value.
          return item;
        };
        const advance = () => {
          this.pending += 1;
          clearTimeout(this.timer);
          void this.ready.then(() => {
            const item = step();
            request.result = item ? {
              value: clone(item.value), key: clone(item.key),
              delete: () => { data().values.delete(keyString(item.key)); },
              continue: () => { position += 1; advance(); },
            } : null;
            request.onsuccess?.();
            this.pending -= 1; this.finishLater();
          });
        };
        advance();
        return request;
      },
    };
  }
}

export function installMemoryIndexedDb() {
  const databases = new Map<string, Db>();
  vi.stubGlobal("indexedDB", {
    open(name: string, version: number) {
      const request: Request & { onupgradeneeded?: () => void } = {};
      queueMicrotask(() => {
        let db = databases.get(name);
        const fresh = !db;
        if (!db) { db = { name, version, stores: new Map(), tail: Promise.resolve() }; databases.set(name, db); }
        const data = db;
        request.result = {
          name, version,
          objectStoreNames: { contains: (store: string) => data.stores.has(store) },
          createObjectStore: (store: string, options?: { keyPath: string }) => {
            data.stores.set(store, { keyPath: options?.keyPath, values: new Map() });
          },
          transaction: (stores: string | string[], mode?: string) =>
            new Transaction(data, typeof stores === "string" ? [stores] : stores, mode === "readwrite"),
          close() {},
        };
        if (fresh) request.onupgradeneeded?.();
        request.onsuccess?.();
      });
      return request;
    },
  });
  const locks = new Map<string, Promise<unknown>>();
  vi.stubGlobal("navigator", { locks: {
    async request<T>(name: string, task: () => Promise<T>) {
      const next = (locks.get(name) ?? Promise.resolve()).catch(() => undefined).then(task);
      locks.set(name, next);
      return next;
    },
  } });
  return databases;
}
