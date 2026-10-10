import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BRAND_SURFACES, deriveBrandPalette } from "../../lib/brandColours";
import { PublicInventoryPage } from "./PublicInventoryPage";

const state = vi.hoisted(() => ({ theme: { primary_color: "#004400", accent_color: "#5a1633" }, mode: "central" }));
vi.mock("../../lib/tenant", () => ({
  useTenant: () => ({ mode: state.mode, slug: "brand", modules: new Set(), bootstrap: { theme: state.theme, branding: {}, modules: [], makerspace: { name: "Brand Space" } } }),
  useTenantPath: () => (subpath = "") => `/m/brand/${subpath}`,
}));
vi.mock("./usePublicInventory", () => ({
  useTenantBootstrap: () => ({ data: { theme: state.theme, branding: {}, modules: [], makerspace: { name: "Brand Space" } } }),
  usePublicCategories: () => ({ data: [] }),
  usePublicInventory: () => ({ data: { results: [], count: 0 } }),
}));
// Request-form authentication is orthogonal to the routed page's token scope.
vi.mock("./PublicRequestPanel", () => ({ PublicRequestPanel: () => null }));

beforeEach(() => {
  state.theme = { primary_color: "#004400", accent_color: "#5a1633" };
  state.mode = "central";
  document.documentElement.className = "";
  vi.spyOn(window, "getComputedStyle").mockImplementation(() => ({
    getPropertyValue: (name: string) => {
      const mode = document.documentElement.classList.contains("dark") ? "dark" : "light";
      const tokens = { secondary: "249 168 212", "on-secondary": "90 22 51",
        bg: BRAND_SURFACES[mode][0].join(" "), surface: BRAND_SURFACES[mode][1].join(" "), panel: BRAND_SURFACES[mode][2].join(" ") };
      return tokens[name.replace("--color-", "") as keyof typeof tokens] ?? "";
    },
  }) as CSSStyleDeclaration);
});
afterEach(() => { vi.restoreAllMocks(); document.documentElement.className = ""; });

function show() {
  return render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><PublicInventoryPage /></MemoryRouter></QueryClientProvider>);
}

it.each(["central", "single"])("renders public derived fill, foreground and interaction tokens in %s mode", (mode) => {
  state.mode = mode;
  show();
  const main = screen.getByRole("main");
  expect(main.style.getPropertyValue("--color-secondary")).toBe("0 68 0");
  expect(main.style.getPropertyValue("--color-on-secondary")).toBe("255 255 255");
  expect(main.style.getPropertyValue("--color-secondary-hover")).toBe("0 63 0");
  expect(main.style.getPropertyValue("--color-secondary-active")).toBe("0 57 0");
  expect(screen.getByRole("button", { name: "Search" })).toHaveClass("desk-button-secondary");
  expect(document.documentElement.style.getPropertyValue("--color-secondary")).toBe("");
  expect(main.style.getPropertyValue("--color-accent")).toBe("");
});

it("rederives ink when dark mode changes without recolouring the staff root", async () => {
  show();
  const main = screen.getByRole("main");
  const lightInk = main.style.getPropertyValue("--color-secondary-ink");
  act(() => document.documentElement.classList.add("dark"));
  const dark = deriveBrandPalette(state.theme, "dark");
  await waitFor(() => expect(main.style.getPropertyValue("--color-secondary-ink")).toBe(dark.ink.join(" ")));
  expect(main.style.getPropertyValue("--color-secondary-ink")).not.toBe(lightInk);
  expect(main.style.getPropertyValue("--color-on-secondary")).toBe("255 255 255");
  expect(document.documentElement.style.getPropertyValue("--color-secondary")).toBe("");
});

it("clears every override on tenant navigation to an invalid stored palette", () => {
  const view = show();
  state.theme = { primary_color: "#777", accent_color: "#5a1633" };
  view.rerender(<QueryClientProvider client={new QueryClient()}><MemoryRouter><PublicInventoryPage /></MemoryRouter></QueryClientProvider>);
  expect(screen.getByRole("main").style.length).toBe(0);
});
