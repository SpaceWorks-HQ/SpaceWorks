// Dependency-free injectManifest build step. Bundle the worker with the SAME Vite
// toolchain, then inject revisions from final emitted bytes, including lazy WASM.
import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { resolve, relative } from "node:path";
import { build, type Plugin, type ResolvedConfig } from "vite";

export function kioskPwa(): Plugin {
  let config: ResolvedConfig;
  return {
    name: "spaceworks-kiosk-inject-manifest", apply: "build", enforce: "post",
    configResolved(value) { config = value; },
    async closeBundle() {
      const output = resolve(config.root, config.build.outDir);
      const entries: { url: string; revision: string }[] = [];
      async function collect(directory: string) {
        for (const file of await readdir(directory, { withFileTypes: true })) {
          const path = resolve(directory, file.name);
          if (file.isDirectory()) await collect(path);
          else {
            const url = relative(output, path).replace(/\\/g, "/");
            if (url === "index.html" || /\.(?:js|css|woff2?|ttf|otf|png|jpe?g|gif|svg|webp|ico|wasm)$/.test(url)) {
              if (url === "config.js" || url === "sw.js") continue;
              entries.push({ url: `/${url}`, revision: createHash("sha256").update(await readFile(path)).digest("hex") });
            }
          }
        }
      }
      await collect(output);
      entries.sort((a, b) => a.url.localeCompare(b.url));
      const worker = await build({
        configFile: false, root: config.root, envDir: config.envDir, mode: config.mode,
        publicDir: false, define: { "self.__WB_MANIFEST": JSON.stringify(entries) },
        build: { write: false, minify: true, target: "es2020",
          rollupOptions: { input: resolve(config.root, "src/sw.ts"),
            output: { format: "es", codeSplitting: false } } },
      });
      if (Array.isArray(worker) || !("output" in worker)) throw new Error("Unexpected worker build output.");
      const chunk = worker.output.find((item) => item.type === "chunk");
      if (!chunk || chunk.type !== "chunk") throw new Error("No service worker generated.");
      await writeFile(resolve(output, "sw.js"), chunk.code);
      // A reviewable artifact independent of minification; verifier also checks
      // every revision occurs in the generated worker itself.
      await writeFile(resolve(output, "pwa-manifest.json"), JSON.stringify(entries, null, 2));
    },
  };
}
