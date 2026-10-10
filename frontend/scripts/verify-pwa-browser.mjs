// Production-worker smoke test against an isolated static server and simulated
// replay transport. No Django/database or real physical handover runs here.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { chromium } from "playwright";

const scratch = resolve("node_modules/.tmp/pwa-browser");
await mkdir(scratch, { recursive: true });
process.env.TMP = scratch; process.env.TEMP = scratch;
const token = "00000000-0000-0000-0000-000000000009";
const commands = new Map();
let uploads = 0;
let base;
const types = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".wasm": "application/wasm", ".svg": "image/svg+xml", ".png": "image/png" };
const server = createServer(async (request, response) => {
  const path = new URL(request.url, base).pathname;
  const json = (value, status = 200) => { response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" }); response.end(JSON.stringify(value)); };
  try {
    if (path === "/config.js") {
      response.writeHead(200, { "Content-Type": "text/javascript", "Cache-Control": "no-store" });
      response.end(`window.__TENANT__={apiUrl:${JSON.stringify(base + "/api")}};`); return;
    }
    if (path === "/upload") {
      for await (const _chunk of request) { /* consume without logging evidence */ }
      uploads += 1; response.writeHead(204); response.end(); return;
    }
    if (path === "/api/v1/health/") { json({ healthy: true }); return; }
    if (path.includes("/replay/")) {
      let body = ""; for await (const chunk of request) body += chunk;
      const envelope = JSON.parse(body);
      assert.equal(request.headers["x-kiosk-operator-lease"], "test-only-lease");
      const previous = commands.get(envelope.client_command_id);
      if (previous) assert.equal(previous.body, body, "Uncertain delivery changed envelope");
      const execute = path.endsWith("/execute/");
      commands.set(envelope.client_command_id, { body, succeeded: previous?.succeeded || execute });
      json({ replay_id: envelope.client_command_id, client_command_id: envelope.client_command_id,
        kind: envelope.kind, state: execute || previous?.succeeded ? "succeeded" : "prepared",
        expires_at: "2999-01-01T00:00:00Z", evidence_id: envelope.evidence ? 9 : null,
        result_request_id: 7, result_loan_id: null, result_return_event_id: null,
        failure_code: null, failure_detail: null,
        ...(envelope.evidence && !execute && !previous?.succeeded ? { upload: {
          evidence_id: 9, object_key: "test-final", upload_url: base + "/upload", method: "PUT",
          headers: { "Content-Type": "image/jpeg" }, fields: {},
        } } : {}) }); return;
    }
    if (path.startsWith("/api/")) { json({ code: "test_api_unavailable" }, 503); return; }
    const file = path.startsWith("/assets/") || extname(path) ? path : "/index.html";
    const absolute = resolve("dist", "." + file);
    assert(absolute.startsWith(resolve("dist") + "/") || absolute.startsWith(resolve("dist") + "\\"));
    response.writeHead(200, { "Content-Type": types[extname(file)] ?? "application/octet-stream", "Cache-Control": "no-cache" });
    response.end(await readFile(absolute));
  } catch { response.writeHead(404); response.end(); }
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
base = `http://127.0.0.1:${server.address().port}`;
let context;
try {
  context = await chromium.launchPersistentContext(resolve(scratch, "profile"), { headless: true });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.error("Browser script error:", error.message));
  const route = `${base}/m/space/kiosk/${token}`;
  await page.goto(route);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);
  await context.setOffline(true);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByText("Reconnect to unlock and load this handover").waitFor().catch(async (error) => {
    console.error("Cold shell state:", await page.locator("body").innerText()); throw error;
  });
  assert.equal(await page.getByLabel("Station PIN").count(), 0);

  // Provision a test-only, previously-online package directly in REAL browser IDB.
  await page.evaluate(async ({ token, base }) => {
    const scope = "1/2/session-test/lease-test/3";
    const state = { version: 1, scope, token, apiBase: base + "/api/v1",
      session: { station: { id: 2, name: "Test desk", kind: "handover" }, makerspace: { id: 1, name: "Space", slug: "space" },
        session_expires_at: "2999-01-01T00:00:00Z", permitted_operations: ["assign_box", "reviewed_issue"] },
      lease: { lease_id: "lease-test", lease_token: "test-only-lease", session_id: "session-test", actor_id: 3,
        expires_at: "2999-01-01T00:00:00Z", permitted_operations: ["assign_box", "reviewed_issue"], allowed_actions: [] },
      works: [{ id: "package-test", aggregateId: "00000000-0000-0000-0000-000000000008", work: {
        kind: "reviewed_request", id: 7, status: "accepted", display_label: "Test request", person_display: "Private test person",
        box: null, lines: [], return_resolutions: [], expires_at: "2999-01-01T00:00:00Z",
        command_age_limit_seconds: 900, evidence_max_bytes: 4 * 1024 * 1024,
      } }], commands: [] };
    const open = indexedDB.open("spaceworks-kiosk-v1", 1);
    open.onupgradeneeded = () => { open.result.createObjectStore("keys"); open.result.createObjectStore("records", { keyPath: "scope" }); open.result.createObjectStore("evidence", { keyPath: "id" }); };
    const db = await new Promise((done, fail) => { open.onsuccess = () => done(open.result); open.onerror = () => fail(open.error); });
    const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv,
      additionalData: new TextEncoder().encode(JSON.stringify(["spaceworks-kiosk-v1", 1, scope, "queue", "lease-test"])) },
    key, new TextEncoder().encode(JSON.stringify(state)));
    const tx = db.transaction(["keys", "records"], "readwrite");
    tx.objectStore("keys").put(key, scope);
    tx.objectStore("records").put({ scope, id: "lease-test", expiresAt: new Date("2999-01-01T00:00:00Z").toISOString(), bytes: ciphertext.byteLength, iv: iv.buffer, ciphertext });
    await new Promise((done, fail) => { tx.oncomplete = done; tx.onabort = () => fail(tx.error); }); db.close();
  }, { token, base });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByLabel("Loaded handover").waitFor();
  await page.getByLabel("Scan box or return QR").fill("TEST-BOX");
  await page.getByRole("button", { name: "Queue handover" }).click();
  await page.getByText(/Sequence 1.*Queued/).waitFor();

  await page.getByRole("combobox", { name: /Operation/ }).selectOption("reviewed_issue");
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas"); canvas.width = 3000; canvas.height = 1500;
    canvas.getContext("2d").fillRect(0, 0, 3000, 1500); return canvas.toDataURL("image/jpeg").split(",")[1];
  });
  const jpeg = Buffer.from(data, "base64");
  const marker = Buffer.from("Exif\0\0PRIVATE-GPS-METADATA");
  const segment = Buffer.alloc(4); segment[0] = 0xff; segment[1] = 0xe1; segment.writeUInt16BE(marker.length + 2, 2);
  await page.getByLabel("Evidence photo", { exact: true }).setInputFiles({ name: "source.jpg", mimeType: "image/jpeg",
    buffer: Buffer.concat([jpeg.subarray(0, 2), segment, marker, jpeg.subarray(2)]) });
  await page.getByRole("button", { name: "Queue handover" }).click();
  await page.getByText(/Sequence 2.*Queued/).waitFor();

  const stored = await page.evaluate(async () => {
    const open = indexedDB.open("spaceworks-kiosk-v1", 1);
    const db = await new Promise((done) => { open.onsuccess = () => done(open.result); });
    const get = (store, key) => new Promise((done) => { const req = db.transaction(store).objectStore(store).get(key); req.onsuccess = () => done(req.result); });
    const key = await get("keys", "1/2/session-test/lease-test/3");
    const images = await new Promise((done) => { const req = db.transaction("evidence").objectStore("evidence").getAll(); req.onsuccess = () => done(req.result); });
    const image = images[0];
    const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: image.iv,
      additionalData: new TextEncoder().encode(JSON.stringify(["spaceworks-kiosk-v1", 1, image.scope, "evidence", image.id])) }, key, image.ciphertext);
    const bitmap = await createImageBitmap(new Blob([clear], { type: "image/jpeg" }));
    const result = { extractable: key.extractable, width: bitmap.width, height: bitmap.height,
      hasMetadata: new TextDecoder().decode(clear).includes("PRIVATE-GPS"), fields: Object.keys(image).sort() };
    bitmap.close(); db.close(); return result;
  });
  assert.equal(stored.extractable, false); assert.equal(stored.width, 1600); assert.equal(stored.height, 800);
  assert.equal(stored.hasMetadata, false);
  assert.deepEqual(stored.fields, ["bytes", "ciphertext", "expiresAt", "id", "iv", "scope"]);
  await context.setOffline(false);
  await page.getByRole("button", { name: "Retry queued work" }).click();
  await page.getByRole("button", { name: "Acknowledge completion and clear local work" }).waitFor();
  assert.equal(commands.size, 2); assert.equal(uploads, 1);
  const cached = await page.evaluate(async () => {
    const keys = []; for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) keys.push(new URL(req.url).pathname);
    return keys;
  });
  assert(cached.includes("/index.html")); assert(cached.some((url) => url.endsWith(".wasm")));
  assert(!cached.some((url) => url.startsWith("/api/") || url === "/config.js" || url === "/upload"));
  console.log("Browser PWA verified: cold shell refusal, real encrypted IDB capture, bounded metadata-free JPEG, ordered replay, static-only cache.");
} finally {
  await context?.close();
  await new Promise((done) => server.close(done));
}
