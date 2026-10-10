import { useSyncExternalStore } from "react";
import type { TenantBootstrap } from "./api";
import { readBrandTokens, tenantColourStyle } from "./branding";
import { currentTheme, subscribeTheme } from "./theme";

// Scope custom colours to this public/member page, including central /m/:slug
// navigation. Putting these on :root would also recolour the staff console.
export function useTenantBranding(bootstrap: TenantBootstrap | null | undefined) {
  const mode = useSyncExternalStore(subscribeTheme, currentTheme);
  const tokens = readBrandTokens();
  return bootstrap && tokens ? tenantColourStyle(bootstrap.theme, tokens, mode) : {};
}
