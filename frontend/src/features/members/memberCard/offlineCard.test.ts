import { beforeEach, expect, it } from "vitest";
import { clearOfflineCards, readOfflineCard, saveOfflineCard, rememberOfflineCardOwner } from "./offlineCard";
const card = { id: 1, name: "Ada", number: 4, space: "Forge", qr: "data:image/png;base64,aGVsbG8=", savedAt: "2026-10-11T00:00:00Z" };
beforeEach(() => { localStorage.clear(); window.history.replaceState(null, "", "/m/forge/member"); });
it("isolates a last-known card by member route and makerspace", () => {
  saveOfflineCard(card); expect(readOfflineCard()).toEqual(card);
  window.history.replaceState(null, "", "/m/other/member"); expect(readOfflineCard()).toBeNull();
});
it("never saves a snapshot on a staff route", () => {
  window.history.replaceState(null, "", "/m/forge/admin"); saveOfflineCard(card);
  expect(localStorage.length).toBe(0);
});
it("clears saved cards without removing unrelated browser preferences", () => {
  saveOfflineCard(card); localStorage.setItem("theme", "dark"); clearOfflineCards();
  expect(readOfflineCard()).toBeNull(); expect(localStorage.getItem("theme")).toBe("dark");
});
it("retains a card on token refresh for the same user and clears it for another user", () => {
  const token = (user_id: number) => `header.${btoa(JSON.stringify({ user_id }))}.signature`;
  rememberOfflineCardOwner(token(1)); saveOfflineCard(card);
  rememberOfflineCardOwner(token(1)); expect(readOfflineCard()).toEqual(card);
  rememberOfflineCardOwner(token(2)); expect(readOfflineCard()).toBeNull();
});
