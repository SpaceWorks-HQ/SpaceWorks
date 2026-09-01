export const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function focusFirstDialogElement(panel: HTMLElement) {
  const target = panel.querySelector<HTMLElement>(focusableSelector) ?? panel;
  target.focus();
}

export function trapDialogFocus(event: KeyboardEvent, panel: HTMLElement) {
  if (event.key !== "Tab") return;
  const items = Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector))
    .filter((item) => !item.hasAttribute("disabled") && item.offsetParent !== null);
  if (!items.length) {
    event.preventDefault();
    panel.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export type DialogEntry = {
  token: symbol;
  previousFocus: HTMLElement | null;
  getPanel: () => HTMLElement | null;
  getLayer: () => HTMLElement | null;
};

let stack: DialogEntry[] = [];
const listeners = new Set<() => void>();
let topToken: symbol | null = null;
let pendingRestore: { previousFocus: HTMLElement | null } | null = null;

function recomputeTop() {
  let topEntry: DialogEntry | null = null;
  let topLayer: HTMLElement | null = null;
  let topZIndex = Number.NEGATIVE_INFINITY;

  for (const entry of stack) {
    const layer = entry.getLayer();
    if (!layer?.isConnected) continue;

    const parsedZIndex = Number.parseFloat(getComputedStyle(layer).zIndex);
    const zIndex = Number.isNaN(parsedZIndex) ? 0 : parsedZIndex;
    const followsCurrent =
      topLayer !== null &&
      Boolean(topLayer.compareDocumentPosition(layer) & Node.DOCUMENT_POSITION_FOLLOWING);

    if (topEntry === null || zIndex > topZIndex || (zIndex === topZIndex && followsCurrent)) {
      topEntry = entry;
      topLayer = layer;
      topZIndex = zIndex;
    }
  }

  topToken = topEntry?.token ?? null;
}

function notifyListeners() {
  listeners.forEach((listener) => listener());
}

function restoreFocus(previousFocus: HTMLElement | null) {
  if (previousFocus?.isConnected) {
    previousFocus.focus();
  } else {
    document.body.focus();
  }
}

export function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function getSnapshot() {
  return topToken;
}

export function pushDialog(entry: Omit<DialogEntry, "token">) {
  const token = Symbol("dialog");
  stack.push({ ...entry, token });
  recomputeTop();
  notifyListeners();
  return token;
}

export function popDialog(token: symbol) {
  const index = stack.findIndex((entry) => entry.token === token);
  if (index === -1) return;

  const wasTopmost = topToken === token;
  const [entry] = stack.splice(index, 1);
  recomputeTop();

  if (wasTopmost) {
    if (topToken === null) {
      pendingRestore = null;
      restoreFocus(entry.previousFocus);
    } else {
      pendingRestore = { previousFocus: entry.previousFocus };
    }
  }

  notifyListeners();
}

export function isTopmost(token: symbol) {
  return topToken === token;
}

export function consumePendingRestore(panel: HTMLElement | null) {
  const pending = pendingRestore;
  if (!pending) return;
  pendingRestore = null;

  const previousFocus = pending.previousFocus;
  if (panel && previousFocus?.isConnected && panel.contains(previousFocus)) {
    previousFocus.focus();
    return;
  }
  if (panel) focusFirstDialogElement(panel);
}
