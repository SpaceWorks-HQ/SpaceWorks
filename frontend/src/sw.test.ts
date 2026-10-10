import { describe, expect, it } from "vitest";
import { cachePolicy } from "./swPolicy";

const origin = "https://space.example";
const paths = new Set(["/index.html", "/assets/kiosk-hash.js", "/assets/zxing-hash.wasm"]);
function policy(path: string, mode: RequestMode = "cors", init: RequestInit = {}) {
  return cachePolicy({ url: path.startsWith("https:") ? path : origin + path, mode,
    method: init.method ?? "GET", headers: new Headers(init.headers) }, origin, paths);
}
describe("generated worker request policy", () => {
  it("supports kiosk-only navigations, never expands offline support to staff/member pages", () => {
    expect(policy("/kiosk/token", "navigate")).toBe("kiosk");
    expect(policy("/m/space/kiosk/token/", "navigate")).toBe("kiosk");
    for (const path of ["/admin", "/m/space/member", "/", "/kiosk", "/kiosk/token/extra"]) {
      expect(policy(path, "navigate")).toBe("network");
    }
  });
  it("caches only exact revisioned static assets, excluding API/auth/evidence/presigns", () => {
    expect(policy("/assets/kiosk-hash.js")).toBe("static");
    expect(policy("/assets/zxing-hash.wasm")).toBe("static");
    for (const path of ["/api/v1/kiosk-stations/token/replay/prepare/", "/api/auth/me", "/evidence/private.jpg", "/config.js",
      "/assets/kiosk-hash.js?signature=secret", "https://storage.example/assets/kiosk-hash.js"]) {
      expect(policy(path)).toBe("network");
    }
    expect(policy("/assets/kiosk-hash.js", "cors", { headers: { Authorization: "Bearer secret" } })).toBe("network");
    expect(policy("/assets/kiosk-hash.js", "cors", { method: "POST" })).toBe("network");
  });
});
