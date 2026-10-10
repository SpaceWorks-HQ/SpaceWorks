import { describe, expect, it } from "vitest";

import { isExpired, KIOSK_IDLE_RESET_MS, resetDelay } from "./kioskSession";

describe("kioskSession", () => {
  const now = Date.parse("2026-10-10T12:00:00Z");

  it("treats missing, unparsable and near-expiry timestamps as expired", () => {
    expect(isExpired(null, now)).toBe(true);
    expect(isExpired("nonsense", now)).toBe(true);
    expect(isExpired("2026-10-10T12:00:03Z", now)).toBe(true);
    expect(isExpired("2026-10-10T13:00:00Z", now)).toBe(false);
  });

  it("resets at the earlier of the idle limit and the server expiry", () => {
    expect(resetDelay("2026-10-10T14:00:00Z", now)).toBe(KIOSK_IDLE_RESET_MS);
    expect(resetDelay("2026-10-10T12:01:00Z", now)).toBe(60_000);
    expect(resetDelay("2026-10-10T11:00:00Z", now)).toBe(0);
    expect(resetDelay(undefined, now)).toBe(KIOSK_IDLE_RESET_MS);
  });
});
