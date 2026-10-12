import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir, access } from "node:fs/promises";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

const output = resolve("dist");
const worker = await readFile(resolve(output, "sw.js"), "utf8");
const manifest = JSON.parse(await readFile(resolve(output, "pwa-manifest.json"), "utf8"));
await assert.rejects(access(resolve("public/sw.js")), "The static public worker must be removed.");
assert(worker.includes("/index.html") && /["'`]navigate["'`]/.test(worker), "Worker must supply navigation shell fallback.");
assert(!worker.includes("skipWaiting"), "Updates must defer while old clients are active.");
assert(manifest.some(({ url }) => url === "/index.html"));
assert(manifest.some(({ url }) => /KioskStationPage.*\.js$/.test(url)), "Lazy kiosk graph missing.");
assert(manifest.some(({ url }) => /zxing_reader.*\.wasm$/.test(url)), "Scanner WASM missing.");
assert(manifest.some(({ url }) => /\.css$/.test(url)), "Styles missing.");
for (const entry of manifest) {
  assert(!/\.map$|\/config\.js$|\/api\//.test(entry.url), "Sensitive/runtime file entered precache.");
  const bytes = await readFile(resolve(output, entry.url.slice(1)));
  assert.equal(entry.revision, createHash("sha256").update(bytes).digest("hex"));
  assert(worker.includes(entry.url) && worker.includes(entry.revision), `Revision absent from worker: ${entry.url}`);
}
for (const asset of await readdir(resolve(output, "assets"))) {
  if (/\.(?:js|css|woff2?|png|svg|webp|wasm)$/.test(asset)) {
    assert(manifest.some(({ url }) => url === `/assets/${asset}`), `Emitted asset absent: ${asset}`);
  }
}
console.log(`PWA verified: ${manifest.length} revisioned shell/assets, kiosk navigation fallback, scanner WASM.`);

const memberWorker = await readFile(resolve(output, "member-sw.js"), "utf8");
assert(!memberWorker.includes("__MEMBER_REVISION__"), "Member shell revision must be injected.");
assert(!manifest.some(entry => entry.url === "/member-sw.js"), "Kiosk must not precache the member worker.");
assert(memberWorker.includes("spaceworks-member-shell-") && !memberWorker.includes("spaceworks-app-shell-"), "Workers must use separate caches.");
assert(!memberWorker.includes("skipWaiting"), "Member updates must wait for active clients.");
for (const scope of ["/member", "/m/forge/member"]) {
  const events = {};
  const cached = [];
  const context = {
    URL, Response, Request, Promise, AbortSignal,
    self: { registration: { scope: `https://example.test${scope}` }, location: { origin: "https://example.test" }, clients: { claim: async () => {} }, addEventListener: (name, handler) => { events[name] = handler; } },
    caches: { open: async () => ({ addAll: async paths => { cached.push(...paths); }, match: async path => new Response(`offline:${path}`) }) },
    fetch: async () => { throw new Error("offline"); },
  };
  runInNewContext(memberWorker, context);
  let installation;
  events.install({ waitUntil: value => { installation = value; } }); await installation;
  assert(cached.length === 5 && cached.every(path => path.startsWith("/member-pwa/")), "Only the dedicated member shell may be cached.");
  for (const path of cached) await access(resolve(output, path.slice(1)));
  const dispatch = async (path, mode = "navigate", headers = new Headers()) => {
    let result;
    events.fetch({ request: { url: `https://example.test${path}`, method: "GET", mode, headers }, respondWith: value => { result = value; } });
    return result ? await result : undefined;
  };
  for (const forbidden of ["/admin", "/m/forge/admin/inventory", "/api/v1/auth/me", "/kiosk/token", "/m/forge/kiosk/token", "/member/archived"]) {
    assert.equal(await dispatch(forbidden), undefined, `Member worker intercepted ${forbidden}`);
  }
  assert.equal(await dispatch(scope, "navigate", new Headers({ Authorization: "Bearer fake" })), undefined);
  const offline = await dispatch(scope);
  assert.equal(await offline.text(), "offline:/member-pwa/offline.html");
  const appManifest = await (await dispatch(`${scope}/manifest.webmanifest?name=Forge`, "same-origin")).json();
  assert.equal(appManifest.scope, scope); assert.equal(appManifest.start_url, scope); assert.equal(appManifest.id, scope);
  assert.equal(appManifest.name, "Forge"); assert.equal(appManifest.display, "standalone");
  assert.deepEqual(appManifest.icons.map(icon => icon.sizes), ["192x192", "512x512"]);
}
const registration = await readFile(resolve("src/components/PwaRegistration.tsx"), "utf8");
assert(registration.includes('scope: member ?? kiosk!'), "Registration must explicitly use separate scopes.");
console.log("Member PWA verified: isolated scopes/caches, installable manifests/icons, no staff/API/kiosk interception.");
