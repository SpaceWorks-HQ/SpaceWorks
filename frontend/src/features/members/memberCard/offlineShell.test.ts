import offlineScript from "../../../../public/member-pwa/offline.js?raw";
import { expect, it } from "vitest";

it("erases an offline card already on screen when another tab logs out", () => {
  const card = document.createElement("section");
  const forget = document.createElement("button");
  const retry = document.createElement("button");
  const loans = document.createElement("div");
  const events = new EventTarget();
  new Function("document", "localStorage", "location", "window", offlineScript)(
    { getElementById: (id: string) => ({ card, forget, retry, loans })[id as "card"], createElement: (tag: string) => document.createElement(tag) },
    { getItem: () => JSON.stringify({ space: "Forge", name: "Private name", number: 9, qr: "data:image/png;base64,eA==", savedAt: "2026-10-11T00:00:00Z" }) },
    { pathname: "/m/forge/member" }, events,
  );
  expect(card.textContent).toContain("Private name");
  events.dispatchEvent(new StorageEvent("storage", { key: "spaceworks.offline-card-owner" }));
  expect(card.textContent).not.toContain("Private name");
  expect(card.querySelector("img")).toBeNull();
});

it("renders only the matching owner's loan projection as text and erases it on logout", () => {
  const panels = Object.fromEntries(["card", "loans", "forget", "retry"].map(id => [id, document.createElement("div")]));
  const events = new EventTarget();
  const saved = { owner: "ada", savedAt: "2026-10-11T00:00:00Z", loans: [{ label: "<script>private-tool</script>", checked_out_at: "2026-10-10T00:00:00Z", due_at: null }] };
  const getItem = (key: string) => key === "spaceworks.offline-card-owner" ? "ada" : key.startsWith("spaceworks.member-loans:") ? JSON.stringify(saved) : null;
  new Function("document", "localStorage", "location", "window", offlineScript)(
    { getElementById: (id: string) => panels[id], createElement: (tag: string) => document.createElement(tag) },
    { getItem }, { pathname: "/m/forge/member" }, events,
  );
  expect(panels.loans.textContent).toContain("Last saved");
  expect(panels.loans.textContent).toContain("<script>private-tool</script>");
  expect(panels.loans.querySelector("script")).toBeNull();
  events.dispatchEvent(new StorageEvent("storage", { key: "spaceworks.offline-card-owner" }));
  expect(panels.loans.textContent).not.toContain("private-tool");
});
