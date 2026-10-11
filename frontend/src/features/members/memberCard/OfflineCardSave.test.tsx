import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { OfflineCardSave } from "./OfflineCardSave";
import { readOfflineCard, saveOfflineCard } from "./offlineCard";
import type { MemberCard } from "./api";

const card: MemberCard = {
  id: 3, card_number: 103, printed_name: "Grace Hopper", membership_id: 12,
  is_active: true, qr_active: true, qr_image: "data:image/png;base64,old",
  photo_set: false, photo_consent_at: null, print_count: 1, last_printed_at: null,
  issued_at: "2026-10-01T00:00:00Z", revoked_at: null, revoked_reason: "",
  created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
};
const checkedAt = Date.parse("2026-10-11T10:00:00Z");
const descriptor = Object.getOwnPropertyDescriptor(navigator, "serviceWorker");
let worker: EventTarget & { controller: { scriptURL: string } | null };
beforeEach(() => {
  window.history.replaceState({}, "", "/m/forge/member");
  window.localStorage.clear();
  worker = Object.assign(new EventTarget(), { controller: { scriptURL: "https://example.test/member-sw.js" } });
  Object.defineProperty(navigator, "serviceWorker", { configurable: true, value: worker });
});
afterEach(() => {
  cleanup();
  if (descriptor) Object.defineProperty(navigator, "serviceWorker", descriptor);
  else Reflect.deleteProperty(navigator, "serviceWorker");
  window.history.replaceState({}, "", "/");
  window.localStorage.clear();
});

it("saves only with explicit consent and lets the member forget the snapshot", () => {
  render(<OfflineCardSave card={card} space="Forge" checkedAt={checkedAt} />);
  expect(readOfflineCard()).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Save card for offline use" }));
  expect(readOfflineCard()).toEqual({ id: 3, name: "Grace Hopper", number: 103, space: "Forge", qr: card.qr_image, savedAt: "2026-10-11T10:00:00.000Z" });
  fireEvent.click(screen.getByRole("button", { name: "Forget offline card" }));
  expect(readOfflineCard()).toBeNull();
});

it("enables saving only once the separate member offline shell controls the page", () => {
  worker.controller = { scriptURL: "https://example.test/sw.js" };
  render(<OfflineCardSave card={card} space="Forge" checkedAt={checkedAt} />);
  expect(screen.getByRole("button", { name: "Save card for offline use" })).toBeDisabled();
  worker.controller = { scriptURL: "https://example.test/member-sw.js" };
  act(() => { worker.dispatchEvent(new Event("controllerchange")); });
  expect(screen.getByRole("button", { name: "Save card for offline use" })).toBeEnabled();
});

it("refreshes an opted-in snapshot with the server QR and actual query check time", () => {
  saveOfflineCard({ id: 3, name: "Old name", number: 103, space: "Forge", qr: "data:image/png;base64,old", savedAt: "2026-10-01T00:00:00Z" });
  render(<OfflineCardSave card={{ ...card, qr_image: "data:image/png;base64,rotated" }} space="Forge" checkedAt={checkedAt} />);
  expect(readOfflineCard()).toMatchObject({ qr: "data:image/png;base64,rotated", savedAt: "2026-10-11T10:00:00.000Z" });
});

it("forgets a revoked snapshot and refuses to save its former QR", () => {
  saveOfflineCard({ id: 3, name: "Grace Hopper", number: 103, space: "Forge", qr: card.qr_image!, savedAt: "2026-10-01T00:00:00Z" });
  render(<OfflineCardSave card={{ ...card, is_active: false, qr_active: false }} space="Forge" checkedAt={checkedAt} />);
  expect(readOfflineCard()).toBeNull();
  expect(screen.getByRole("button", { name: "Save card for offline use" })).toBeDisabled();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
