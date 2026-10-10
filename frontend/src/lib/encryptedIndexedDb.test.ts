// @vitest-environment node
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { installMemoryIndexedDb } from "../test/memoryIndexedDb";
import { openEncryptedDatabase, keyFor, readKey, encryptBytes, decryptBytes, deleteScopes, requestValue, transactionDone } from "./encryptedIndexedDb";

beforeEach(() => { installMemoryIndexedDb(); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("shared encrypted IDB primitive", () => {
  it("clones a non-extractable AES-256 key and uses fresh 96-bit IVs", async () => {
    const db = await openEncryptedDatabase("test", 1, [{ name: "keys" }, { name: "records", keyPath: "scope" }]);
    const [key, second] = await Promise.all([keyFor(db, "s"), keyFor(db, "s")]);
    const stored = (await readKey(db, "s"))!;
    expect(stored.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("raw", stored)).rejects.toThrow();
    const bytes = new TextEncoder().encode("private").buffer;
    const a = await encryptBytes(key, bytes, "scope/kind/id");
    const b = await encryptBytes(second, bytes, "scope/kind/id");
    expect(a.iv.byteLength).toBe(12);
    expect(new Uint8Array(a.iv)).not.toEqual(new Uint8Array(b.iv));
    expect(new TextDecoder().decode(await decryptBytes(stored, b, "scope/kind/id"))).toBe("private");
    expect(new TextDecoder().decode(await decryptBytes(stored, a, "scope/kind/id"))).toBe("private");
    await expect(decryptBytes(stored, a, "other-scope/kind/id")).rejects.toThrow();
    const tampered = { ...a, ciphertext: a.ciphertext.slice(0) };
    new Uint8Array(tampered.ciphertext)[0] ^= 1;
    await expect(decryptBytes(stored, tampered, "scope/kind/id")).rejects.toThrow();
    db.close();
  });

  it("destroys scoped keys and ciphertext together, preserving other scopes", async () => {
    const db = await openEncryptedDatabase("test", 1, [{ name: "keys" }, { name: "records", keyPath: "scope" }]);
    await keyFor(db, "a"); await keyFor(db, "b");
    const tx = db.transaction("records", "readwrite");
    const done = transactionDone(tx);
    tx.objectStore("records").put({ scope: "a", ciphertext: "opaque" });
    tx.objectStore("records").put({ scope: "b", ciphertext: "opaque" });
    await done;
    await deleteScopes(db, ["records"], ["a"]);
    expect(await readKey(db, "a")).toBeUndefined();
    expect(await readKey(db, "b")).toBeDefined();
    expect(await requestValue(db.transaction("records").objectStore("records").get("a"))).toBeUndefined();
    expect(await requestValue(db.transaction("records").objectStore("records").get("b"))).toBeDefined();
    db.close();
  });
});
