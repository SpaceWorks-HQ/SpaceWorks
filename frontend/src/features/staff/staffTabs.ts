import { featureEnabled } from "../../lib/features";
import type { Makerspace } from "./panels/shared";
import { readStorage, removeStorage, writeStorage } from "../../lib/safeStorage";

const TAB_MODULES: Record<string, string[]> = {
  direct: ["public_inventory"],
  printing: ["printing"],
  events: ["events"],
  bookings: ["bookings"],
  tobuy: ["procurement"],
  transfers: ["stock_transfers"],
  stocktake: ["stocktake"],
  containers: ["containers"],
  bulk: ["bulk_import"],
  qr: ["qr_management"],
  scanner: ["scanner"],
  reports: ["reports"],
  warranty: ["staff_admin"],
};

// Tabs whose backing app can be tombstoned out of a deployment but which no module
// key describes. `warranty` is gated by core `staff_admin`, so dropping a module key
// cannot hide it -- without this the tab would survive the tombstone and 404 on every
// request. Tabs that do have their own key need no entry: the server already omits a
// tombstoned app's key from `enabled_modules`.
const TAB_APPS: Record<string, string> = {
  warranty: "warranty",
};

const TAB_PATHS: Record<string, string> = {
  direct: "direct-handout",
  needsfix: "to-be-fixed",
  tobuy: "to-buy",
  bulk: "bulk-import",
  qr: "qr-tools",
  api: "api-access",
  emailtemplates: "email-templates",
  "email-logs": "email-log",
};

const PATH_TABS = Object.fromEntries(
  Object.entries(TAB_PATHS).map(([tab, path]) => [path, tab]),
);

export const STAFF_SELECTED_MAKERSPACE_KEY = "spaceworks.staff.selectedMakerspace";
export const STAFF_ACTIVE_TAB_KEY = "spaceworks.staff.activeTab";

export function filterTabsByEnabledModules(tabs: readonly string[], makerspace?: Makerspace) {
  const unavailable = new Set(makerspace?.unavailable_apps ?? []);
  // Checked before the module gate and outside the early return below: an app the
  // deployment does not ship is unreachable no matter what the tenant enabled, and a
  // makerspace row that has not loaded its modules yet must not show it either.
  const shipped = tabs.filter((tabName) => !unavailable.has(TAB_APPS[tabName] ?? ""));

  const modules = makerspace?.enabled_modules;
  if (!modules) return shipped;
  const enabled = new Set(modules);
  return shipped.filter((tabName) => {
    if (tabName === "direct") {
      return featureEnabled(makerspace.enabled_features ?? [], "inventory.self_checkout");
    }
    const required = TAB_MODULES[tabName];
    return !required || required.some((moduleName) => enabled.has(moduleName));
  });
}

export function readStoredMakerspace() {
  const value = Number(readStorage(STAFF_SELECTED_MAKERSPACE_KEY));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function readStoredStaffTab() {
  return pathToTab(readStorage(STAFF_ACTIVE_TAB_KEY));
}

export function persistSelectedMakerspace(value: number | null) {
  if (value === null) removeStorage(STAFF_SELECTED_MAKERSPACE_KEY);
  else writeStorage(STAFF_SELECTED_MAKERSPACE_KEY, String(value));
}

export function persistStaffTab(tab: string) {
  if (tab) writeStorage(STAFF_ACTIVE_TAB_KEY, tab);
  else removeStorage(STAFF_ACTIVE_TAB_KEY);
}

export function staffBasePath(guestOnly: boolean) {
  return guestOnly ? "/guest-admin" : "/admin";
}

export function staffTabPath(
  tab: string,
  guestOnly: boolean,
  makerspaceSlug?: string | null,
  singleTenantLocked = false,
) {
  const pagePath = tabToPath(tab);
  if (makerspaceSlug && !singleTenantLocked) {
    return `/m/${makerspaceSlug}/admin/${pagePath}`;
  }
  return `${staffBasePath(guestOnly)}/${pagePath}`;
}

export function staffPathState(pathname: string, guestOnly: boolean) {
  const scoped = /^\/m\/([^/]+)\/admin(?:\/([^/]+))?/.exec(pathname);
  if (scoped) {
    return { makerspaceSlug: scoped[1], tab: pathToTab(scoped[2] ?? "") };
  }

  const basePath = staffBasePath(guestOnly);
  if (!pathname.startsWith(basePath)) {
    return { makerspaceSlug: "", tab: "" };
  }
  const relative = pathname.slice(basePath.length).replace(/^\/+/, "");
  return { makerspaceSlug: "", tab: pathToTab(relative.split("/")[0] ?? "") };
}

export function staffMakerspaceSlugFromPath(pathname: string, guestOnly: boolean) {
  return staffPathState(pathname, guestOnly).makerspaceSlug;
}

export function tabFromStaffPath(pathname: string, guestOnly: boolean) {
  return staffPathState(pathname, guestOnly).tab;
}

export function tabToPath(tab: string) {
  return TAB_PATHS[tab] ?? tab;
}

function pathToTab(path: string | null) {
  if (path === "printing") return "machines";
  if (!path) {
    return "";
  }
  return PATH_TABS[path] ?? path;
}
