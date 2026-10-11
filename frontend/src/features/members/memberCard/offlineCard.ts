import { memberScope } from "../../../lib/pwaScopes";
import { readStorage, removeStorage, writeStorage } from "../../../lib/safeStorage";

export const OFFLINE_CARD_PREFIX = "spaceworks.member-card:";
const OWNER_KEY = "spaceworks.offline-card-owner";
export type OfflineCard = { id: number; name: string; number: number; space: string; qr: string; savedAt: string };
export const offlineCardKey = () => OFFLINE_CARD_PREFIX + (memberScope(window.location.pathname) ?? "");
export function readOfflineCard(): OfflineCard | null {
  try {
    const value = JSON.parse(readStorage(offlineCardKey(), "null"));
    return value && typeof value.id === "number" && typeof value.name === "string" && typeof value.qr === "string" ? value : null;
  } catch { return null; }
}
export function saveOfflineCard(card: OfflineCard) {
  if (memberScope(window.location.pathname)) writeStorage(offlineCardKey(), JSON.stringify(card));
}
export function forgetOfflineCard() { removeStorage(offlineCardKey()); }
export function clearOfflineCards() {
  try {
    const keys = Object.keys(window.localStorage).filter(key => key.startsWith(OFFLINE_CARD_PREFIX));
    keys.forEach(removeStorage);
    removeStorage(OWNER_KEY);
  } catch { /* Storage may be disabled. */ }
}

/** JWT decoding here is only a cache privacy boundary, never authorization. */
export function rememberOfflineCardOwner(token: string) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    const owner = String(payload.user_id ?? payload.sub ?? "");
    if (!owner) { clearOfflineCards(); return; }
    const previous = readStorage(OWNER_KEY);
    if (previous !== owner) clearOfflineCards();
    writeStorage(OWNER_KEY, owner);
    return owner;
  } catch { clearOfflineCards(); }
}
