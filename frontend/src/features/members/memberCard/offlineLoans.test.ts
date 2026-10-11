import { beforeEach, expect, it, vi } from "vitest";
import { clearOfflineCards, forgetOfflineCard, forgetOfflineMemberData, rememberOfflineCardOwner } from "./offlineCard";
import { OFFLINE_LOANS_PREFIX, readOfflineLoans, saveOfflineLoans } from "./offlineLoans";
const loan = { label: "Drill", checked_out_at: "2026-10-10T10:00:00Z", due_at: "2026-10-15T10:00:00Z", private_evidence: "secret" };
const token = (user_id: number) => `header.${btoa(JSON.stringify({ user_id }))}.signature`;
beforeEach(() => { localStorage.clear(); window.history.replaceState(null, "", "/m/lab/member"); rememberOfflineCardOwner(token(1)); });
it("saves only the own-loan projection with a stale timestamp", () => {
  saveOfflineLoans("Lab", [loan]);
  expect(readOfflineLoans()?.loans).toEqual([{ label: loan.label, checked_out_at: loan.checked_out_at, due_at: loan.due_at }]);
  expect(readOfflineLoans()?.savedAt).toBeTruthy();
  expect(JSON.stringify(readOfflineLoans())).not.toContain("secret");
});
it("isolates tenants and refuses saving on staff routes", () => {
  saveOfflineLoans("Lab", [loan]); window.history.replaceState(null, "", "/m/other/member"); expect(readOfflineLoans()).toBeNull();
  window.history.replaceState(null, "", "/admin"); saveOfflineLoans("Other", [loan]);
  expect(Object.keys(localStorage).filter(key => key.startsWith(OFFLINE_LOANS_PREFIX))).toHaveLength(1);
});
it("retains same-owner refresh but clears logout and account switch", () => {
  saveOfflineLoans("Lab", [loan]); rememberOfflineCardOwner(token(1)); expect(readOfflineLoans()).not.toBeNull();
  rememberOfflineCardOwner(token(2)); expect(readOfflineLoans()).toBeNull();
  saveOfflineLoans("Lab", [loan]); clearOfflineCards(); expect(readOfflineLoans()).toBeNull();
});
it("refuses corrupt and wrong-owner snapshots", () => {
  localStorage.setItem(`${OFFLINE_LOANS_PREFIX}/m/lab/member`, JSON.stringify({ owner: "2", space: "Lab", savedAt: "yesterday", loans: [] }));
  expect(readOfflineLoans()).toBeNull();
});
it("keeps separate opt-ins but clears both when member authority is refused", () => {
  saveOfflineLoans("Lab", [loan]); forgetOfflineCard(); expect(readOfflineLoans()).not.toBeNull();
  forgetOfflineMemberData(); expect(readOfflineLoans()).toBeNull();
});
it("does not report a saved projection when device storage is unavailable", () => {
  const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage disabled"); });
  try { expect(saveOfflineLoans("Lab", [loan])).toBe(false); expect(readOfflineLoans()).toBeNull(); }
  finally { write.mockRestore(); }
});
