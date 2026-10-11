import { expect, it } from "vitest";
import { filterTabsByEnabledModules } from "./staffTabs";
import { getStaffAccess } from "./staffAccess";

const core = ["public_inventory", "request_workflow", "staff_admin", "qr_management", "evidence_uploads", "scanner"];
const allTabs = getStaffAccess([], true, false).allowedTabs;
const loans = ["requests", "inventory", "categories", "needsfix", "ledger", "accountability", "warranty", "direct", "scanner"];

it.each(["events", "machines", "membership", "bookings", "inventory"])("shows only the selected %s family and shared administration", (family) => {
  const tabs = filterTabsByEnabledModules(allTabs, {
    enabled_modules: [...core, ...(family === "inventory" ? [] : [family])],
    enabled_features: family === "inventory" ? ["loans.enabled", "inventory.self_checkout"] : [],
  });
  for (const tab of loans.filter((tab) => allTabs.includes(tab)))
    expect(tabs.includes(tab)).toBe(family === "inventory" || (tab === "warranty" && family === "machines"));
  for (const tab of ["events", "machines", "bookings"]) expect(tabs.includes(tab)).toBe(family === tab);
  for (const tab of ["dashboard", "settings", "users", "audit", "members", "modules"]) expect(tabs).toContain(tab);
});

it("suppresses loan tabs even when optional inventory modules remain installed", () => {
  const tabs = filterTabsByEnabledModules(allTabs, { enabled_modules: [...core, "containers", "stocktake", "bulk_import", "qr_print_batches", "stock_transfers"], enabled_features: [] });
  for (const tab of [...loans, "containers", "stocktake", "bulk", "qr", "transfers"]) expect(tabs).not.toContain(tab);
});

it("turning loans back on restores tabs without reinstalling modules", () => {
  const modules = [...core, "events"];
  const before = [...modules];
  expect(filterTabsByEnabledModules(["requests", "events"], { enabled_modules: modules, enabled_features: [] })).toEqual(["events"]);
  expect(filterTabsByEnabledModules(["requests", "events"], { enabled_modules: modules, enabled_features: ["loans.enabled"] })).toEqual(["requests", "events"]);
  expect(modules).toEqual(before);
});

it.each(["manage_events", "manage_bookings", "manage_members", "view_finance"])("admits %s custom staff to their dashboard", (action) => {
  expect(getStaffAccess([action], false, false).allowedTabs).toContain("dashboard");
});
