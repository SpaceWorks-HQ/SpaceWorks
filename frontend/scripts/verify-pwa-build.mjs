import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir, access } from "node:fs/promises";
import { resolve } from "node:path";

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
