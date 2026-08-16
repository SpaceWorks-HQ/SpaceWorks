import { featureEnabled } from "../../lib/features";
import type { Makerspace } from "./panels/shared";
import { readStorage, removeStorage, writeStorage } from "../../lib/safeStorage";

// The single map from a staff tab to the module key(s) its backend surface is guarded by.
// `getStaffAccess` decides permissions and nothing else -- a tab named in both places is
// how one ends up gated in the sidebar but not on the route.
//
// A tab is listed only when a module can genuinely remove it. Three are deliberately
// absent, each for a reason that looks like an oversight:
//   * `members`    -- the panel mixes the never-gated staff roster and role assignment
//                     with the membership-gated community queue. Gating the tab would let
//                     a space lock itself out of its own administration (plan A7), so the
//                     module is applied to the sections inside it instead.
//   * `email-logs` -- a message blocked by the `email` module is recorded as a terminal
//                     SKIPPED row precisely so the operator can see what the toggle
//                     suppressed. Gating the log would hide the evidence it exists to show.
//   * `emailtemplates` -- gated per stream by the server; the hardware and printing
//                     streams are always present, so the tab always has content.
const TAB_MODULES: Record<string, string[]> = {
  direct: ["public_inventory"],
  notifications: ["notifications"],
  printing: ["printing"],
  machines: ["machines"],
  handover: ["machine_service"],
  events: ["events"],
  bookings: ["bookings"],
  tobuy: ["procurement"],
  transfers: ["stock_transfers"],
  stocktake: ["stocktake"],
  containers: ["containers"],
  bulk: ["bulk_import"],
  // Not the core `qr_management`, which no operator can switch off and which therefore
  // gated nothing. Every action in QrTools is batch-scoped -- `canAddItemQr`,
  // `canReprintAsset` and `canGenerateAssets` all require a selected batch -- so without
  // this module the tab is a form whose every submission 404s. Core QR issuance is still
  // reachable from the scanner and inventory panels.
  qr: ["qr_print_batches"],
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
  modules: "modules",
  exports: "data-export",
};

const PATH_TABS = Object.fromEntries(
  Object.entries(TAB_PATHS).map(([tab, path]) => [path, tab]),
);

export const STAFF_SELECTED_MAKERSPACE_KEY = "spaceworks.staff.selectedMakerspace";
export const STAFF_ACTIVE_TAB_KEY = "spaceworks.staff.activeTab";

// Only the two capability fields, not the whole Makerspace. A full row satisfies this
// structurally, so every caller is unaffected -- and it stops the signature from claiming
// a dependency on identity fields (slug, domain, chat id) that this never reads.
type TabCapabilities = Pick<
  Makerspace,
  "enabled_modules" | "enabled_features" | "unavailable_apps"
>;

export function filterTabsByEnabledModules(tabs: readonly string[], makerspace?: TabCapabilities) {
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

// Tabs allowed to carry a subpath. Everything else NORMALISES trailing segments away, and
// that behaviour is deliberate: a stale deep link to `/admin/inventory/whatever` should land
// on the inventory tab, not 404. Relaxing it globally would change how every existing
// bookmark resolves, so the exception is opt-in and currently holds exactly one tab.
const TABS_WITH_SUBPATHS = new Set(["machines"]);

export function staffTabPath(
  tab: string,
  guestOnly: boolean,
  makerspaceSlug?: string | null,
  singleTenantLocked = false,
  subPath = "",
) {
  const pagePath = tabToPath(tab);
  const suffix = subPath && TABS_WITH_SUBPATHS.has(tab) ? `/${subPath}` : "";
  if (makerspaceSlug && !singleTenantLocked) {
    return `/m/${makerspaceSlug}/admin/${pagePath}${suffix}`;
  }
  return `${staffBasePath(guestOnly)}/${pagePath}${suffix}`;
}

export function staffPathState(pathname: string, guestOnly: boolean) {
  const scoped = /^\/m\/([^/]+)\/admin(?:\/([^/]+))?(?:\/(.*))?$/.exec(pathname);
  if (scoped) {
    return {
      makerspaceSlug: scoped[1],
      tab: pathToTab(scoped[2] ?? ""),
      subPath: trimSlashes(scoped[3] ?? ""),
    };
  }

  const basePath = staffBasePath(guestOnly);
  if (!pathname.startsWith(basePath)) {
    return { makerspaceSlug: "", tab: "", subPath: "" };
  }
  const relative = pathname.slice(basePath.length).replace(/^\/+/, "");
  const [first, ...rest] = relative.split("/");
  return {
    makerspaceSlug: "",
    tab: pathToTab(first ?? ""),
    subPath: trimSlashes(rest.join("/")),
  };
}

export function staffSubPathFromPath(pathname: string, guestOnly: boolean) {
  return staffPathState(pathname, guestOnly).subPath;
}

/** Which subpath survives `StaffWorkspace`'s canonicalization of the URL.
 *
 * Extracted so the rule is testable. `StaffWorkspace` rewrites the location to the
 * canonical path for the active tab, and while that path was built without the subpath a
 * per-type deep link could never survive its first render: `/admin/machines/12-laser` and
 * `/admin/machines` differ, so the redirect fired on every load and stripped the segment.
 *
 * The subpath is kept ONLY when the route already resolved to the tab being rendered.
 * Otherwise the requested tab was denied, unavailable or absent, the actor is being sent
 * somewhere else, and carrying a machine-type segment onto a different tab would be
 * meaningless at best.
 */
export function keptStaffSubPath(routeTab: string, activeTab: string, routeSubPath: string) {
  return routeTab && routeTab === activeTab ? routeSubPath : "";
}

function trimSlashes(value: string) {
  return value.replace(/^\/+|\/+$/g, "");
}

// --- machine-type subpages -------------------------------------------------------------
//
// THE ID IS AUTHORITATIVE AND THE SLUG IS DECORATION. Machine-type slug uniqueness is only
// SCOPED -- `uniq_global_machinetype_slug` among globals, `uniq_lab_machinetype_slug` per
// makerspace -- so a makerspace may legally own a local type slugged `3d_printer` while the
// global built-in of that slug also exists, and both appear in one console. Three shipped
// surfaces have already served one type's jobs under another by keying on the slug. The
// slug rides along only so the URL is readable.

export function machineTypeSegment(machineType: { id: number; slug?: string | null }) {
  const slug = (machineType.slug ?? "").trim();
  return slug ? `${machineType.id}-${slug}` : String(machineType.id);
}

export function parseMachineTypeSegment(segment: string): number | null {
  // Leading integer only. A malformed segment is `null` -- "no type selected", i.e. the
  // index -- and never a silent fall-through to some default type.
  const match = /^(\d+)/.exec(segment.trim());
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
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
