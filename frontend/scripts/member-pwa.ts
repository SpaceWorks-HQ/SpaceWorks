import { deflateSync } from "node:zlib";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { Plugin, ResolvedConfig } from "vite";

// Small built-in raster icons, so installability never depends on a tenant logo
// being square, public, available, or a supported bitmap format.
function icon(size: number) {
  const crc = (bytes: Buffer) => {
    let value = 0xffffffff;
    for (const byte of bytes) {
      value ^= byte;
      for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
    }
    return (value ^ 0xffffffff) >>> 0;
  };
  const chunk = (name: string, bytes: Buffer) => {
    const type = Buffer.from(name);
    const length = Buffer.alloc(4); length.writeUInt32BE(bytes.length);
    const checksum = Buffer.alloc(4); checksum.writeUInt32BE(crc(Buffer.concat([type, bytes])));
    return Buffer.concat([length, type, bytes, checksum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size); header.writeUInt32BE(size, 4); header[8] = 8; header[9] = 2;
  const pixels = Buffer.alloc(size * (size * 3 + 1));
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const mark = x > size * .25 && x < size * .75 && (
      (y > size * .25 && y < size * .34) || (y > size * .46 && y < size * .55)
      || (y > size * .67 && y < size * .76) || (x < size * .34 && y > size * .25 && y < size * .55)
      || (x > size * .66 && y > size * .46 && y < size * .76));
    const offset = y * (size * 3 + 1) + 1 + x * 3;
    pixels.set(mark ? [255, 255, 255] : [30, 51, 63], offset);
  }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(pixels)), chunk("IEND", Buffer.alloc(0))]);
}

export function memberPwa(): Plugin {
  let config: ResolvedConfig;
  return {
    name: "spaceworks-member-icons", apply: "build",
    configResolved(value) { config = value; },
    generateBundle() {
      for (const size of [192, 512]) this.emitFile({ type: "asset", fileName: `member-pwa/icon-${size}.png`, source: icon(size) });
    },
    async closeBundle() {
      const output = resolve(config.root, config.build.outDir);
      const worker = await readFile(resolve(output, "member-sw.js"), "utf8");
      const revision = createHash("sha256").update(worker);
      for (const file of ["offline.html", "offline.js", "offline.css", "icon-192.png", "icon-512.png"]) {
        revision.update(await readFile(resolve(output, "member-pwa", file)));
      }
      await writeFile(resolve(output, "member-sw.js"), worker.replace("__MEMBER_REVISION__", revision.digest("hex")));
    },
  };
}
