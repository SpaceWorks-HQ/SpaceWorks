import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PwaRegistration } from "../components/PwaRegistration";
import { kioskScope, memberScope } from "./pwaScopes";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
describe("separate PWA registration scopes", () => {
  it.each([
    ["/member", "/member", null], ["/m/forge/member", "/m/forge/member", null],
    ["/kiosk/token", null, "/kiosk/"], ["/m/forge/kiosk/token", null, "/m/forge/kiosk/"],
    ["/admin/inventory", null, null], ["/m/forge/admin", null, null], ["/member/archived", null, null],
  ])("maps %s to non-overlapping member and kiosk scopes", (path, member, kiosk) => {
    expect(memberScope(path)).toBe(member); expect(kioskScope(path)).toBe(kiosk);
  });
  it.each([["/m/forge/member", "/member-sw.js", "/m/forge/member"], ["/m/forge/kiosk/token", "/sw.js", "/m/forge/kiosk/"]])("registers the correct worker for %s and retires only the root worker", async (path, script, scope) => {
    vi.stubEnv("PROD", true);
    const unregister = vi.fn(); const keep = vi.fn(); const register = vi.fn();
    Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: {
      register, getRegistrations: async () => [{ scope: "https://example.test/", unregister }, { scope: "https://example.test/kiosk/", unregister: keep }],
    } });
    render(<MemoryRouter initialEntries={[path]}><PwaRegistration /></MemoryRouter>);
    await waitFor(() => expect(register).toHaveBeenCalledWith(script, { scope, updateViaCache: "none" }));
    expect(unregister).toHaveBeenCalledTimes(1); expect(keep).not.toHaveBeenCalled();
  });
});
