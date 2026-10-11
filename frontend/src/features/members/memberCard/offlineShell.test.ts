import offlineScript from "../../../../public/member-pwa/offline.js?raw";
import { expect, it } from "vitest";

it("erases an offline card already on screen when another tab logs out", () => {
  const card = document.createElement("section");
  const forget = document.createElement("button");
  const retry = document.createElement("button");
  const events = new EventTarget();
  new Function("document", "localStorage", "location", "window", offlineScript)(
    { getElementById: (id: string) => ({ card, forget, retry })[id as "card"], createElement: (tag: string) => document.createElement(tag) },
    { getItem: () => JSON.stringify({ space: "Forge", name: "Private name", number: 9, qr: "data:image/png;base64,eA==", savedAt: "2026-10-11T00:00:00Z" }) },
    { pathname: "/m/forge/member" }, events,
  );
  expect(card.textContent).toContain("Private name");
  events.dispatchEvent(new StorageEvent("storage", { key: "spaceworks.offline-card-owner" }));
  expect(card.textContent).not.toContain("Private name");
  expect(card.querySelector("img")).toBeNull();
});
