import { afterEach, describe, expect, it, vi } from "vitest";

import {
  consumePendingRestore,
  getSnapshot,
  isTopmost,
  popDialog,
  pushDialog,
} from "./dialogFocus";

const tokens: symbol[] = [];

function addLayer(zIndex = "0") {
  const layer = document.createElement("div");
  layer.style.zIndex = zIndex;
  document.body.append(layer);
  return layer;
}

function pushLayer(layer: HTMLElement, previousFocus: HTMLElement | null = null) {
  const panel = document.createElement("div");
  layer.append(panel);
  const token = pushDialog({
    previousFocus,
    getPanel: () => panel,
    getLayer: () => layer,
  });
  tokens.push(token);
  return token;
}

afterEach(() => {
  while (tokens.length) popDialog(tokens.pop()!);
  consumePendingRestore(null);
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("dialog focus store", () => {
  it("tracks the top through push and order-independent, idempotent pops", () => {
    const first = pushLayer(addLayer("10"));
    const second = pushLayer(addLayer("20"));

    expect(getSnapshot()).toBe(second);
    expect(isTopmost(second)).toBe(true);

    popDialog(first);
    popDialog(first);
    popDialog(Symbol("unknown"));
    expect(getSnapshot()).toBe(second);

    popDialog(second);
    expect(getSnapshot()).toBeNull();
  });

  it("uses document order to break equal-z ties", () => {
    const earlierLayer = addLayer("100");
    const laterLayer = addLayer("100");

    const later = pushLayer(laterLayer);
    pushLayer(earlierLayer);

    expect(getSnapshot()).toBe(later);
  });

  it("lets a higher z-index win regardless of push order", () => {
    const highLayer = addLayer("200");
    const lowLayer = addLayer("50");

    const high = pushLayer(highLayer);
    pushLayer(lowLayer);

    expect(getSnapshot()).toBe(high);
  });

  it("does not queue focus restoration when a non-top entry is popped", () => {
    const lowerOpener = document.createElement("button");
    const currentFocus = document.createElement("button");
    const topPanel = document.createElement("div");
    const topFirst = document.createElement("button");
    document.body.append(lowerOpener, currentFocus);

    const lower = pushLayer(addLayer("10"), lowerOpener);
    const topLayer = addLayer("20");
    topPanel.append(topFirst);
    topLayer.append(topPanel);
    const top = pushDialog({
      previousFocus: null,
      getPanel: () => topPanel,
      getLayer: () => topLayer,
    });
    tokens.push(top);

    currentFocus.focus();
    popDialog(lower);
    consumePendingRestore(topPanel);

    expect(document.activeElement).toBe(currentFocus);
  });

  it("restores a connected opener immediately when the last dialog pops", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    const token = pushLayer(addLayer("10"), opener);

    popDialog(token);

    expect(document.activeElement).toBe(opener);
  });

  it("falls back to document.body when the last dialog's opener is detached", () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    const token = pushLayer(addLayer("10"), opener);
    opener.remove();
    const bodyFocus = vi.spyOn(document.body, "focus");

    popDialog(token);

    expect(bodyFocus).toHaveBeenCalledOnce();
  });
});
