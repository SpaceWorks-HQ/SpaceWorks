import { readStorage, writeStorage } from "./safeStorage";

export type Theme = "light" | "dark";
export const THEME_KEY = "makerspace.theme";
let sessionChoice: Theme | undefined;

export function preferredTheme(): Theme {
  if (sessionChoice) return sessionChoice;
  const stored = readStorage(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function applyTheme() {
  document.documentElement.classList.toggle("dark", preferredTheme() === "dark");
}

// Called before React mounts, including pages without a toggle. An OS change is
// followed only while there is no explicit choice; it never writes to storage.
export function initializeTheme() {
  sessionChoice = undefined;
  applyTheme();
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  media?.addEventListener("change", applyTheme);
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_KEY || event.key === null) {
      sessionChoice = undefined;
      applyTheme();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    media?.removeEventListener("change", applyTheme);
    window.removeEventListener("storage", onStorage);
  };
}

export function chooseTheme(theme: Theme) {
  sessionChoice = theme;
  writeStorage(THEME_KEY, theme);
  // Still works when localStorage is unavailable.
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}
