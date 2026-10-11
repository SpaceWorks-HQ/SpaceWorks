import { memberScope } from "../../../lib/pwaScopes";
import { readStorage, removeStorage, writeStorage } from "../../../lib/safeStorage";

export const OFFLINE_LOANS_PREFIX = "spaceworks.member-loans:";
export const OFFLINE_OWNER_KEY = "spaceworks.offline-card-owner";
export type OfflineLoan = { label: string; checked_out_at: string; due_at: string | null };
export type OfflineLoans = { owner: string; space: string; savedAt: string; loans: OfflineLoan[] };
const key = () => OFFLINE_LOANS_PREFIX + (memberScope(window.location.pathname) ?? "");

export function readOfflineLoans(): OfflineLoans | null {
  try {
    if (!memberScope(window.location.pathname)) return null;
    const row = JSON.parse(readStorage(key(), "null"));
    if (!row || !row.owner || row.owner !== readStorage(OFFLINE_OWNER_KEY) || typeof row.space !== "string" || !Number.isFinite(Date.parse(row.savedAt)) || !Array.isArray(row.loans) || row.loans.length > 200) return null;
    if (row.loans.some((loan: OfflineLoan) => typeof loan.label !== "string" || !Number.isFinite(Date.parse(loan.checked_out_at)) || (loan.due_at !== null && !Number.isFinite(Date.parse(loan.due_at))))) return null;
    return row;
  } catch { return null; }
}

/** Explicit opt-in projection of the member's own activity; no API cache or authority. */
export function saveOfflineLoans(space: string, loans: readonly OfflineLoan[]) {
  const owner = readStorage(OFFLINE_OWNER_KEY);
  if (!owner || !memberScope(window.location.pathname)) return false;
  const snapshot = JSON.stringify({ owner, space, savedAt: new Date().toISOString(),
    loans: loans.slice(0, 200).map(loan => ({ label: loan.label.slice(0, 300), checked_out_at: loan.checked_out_at, due_at: loan.due_at })) });
  writeStorage(key(), snapshot);
  return readStorage(key()) === snapshot;
}
export function forgetOfflineLoans() { removeStorage(key()); }
export function clearOfflineLoans() {
  try { Object.keys(window.localStorage).filter(value => value.startsWith(OFFLINE_LOANS_PREFIX)).forEach(removeStorage); } catch { /* Storage can be disabled. */ }
}
