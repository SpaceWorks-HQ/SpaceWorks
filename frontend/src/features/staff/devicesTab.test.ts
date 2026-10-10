import { describe, expect, it } from "vitest";
import { getStaffAccess, TAB_GROUPS, TAB_LABELS } from "./staffAccess";
import { filterTabsByEnabledModules, staffTabPath, tabFromStaffPath } from "./staffTabs";

describe("Devices tab matches the identity API authority available in lane 7a", () => {
  it.each([[], ["manage_machines"], ["manage_qr"], ["manage_makerspace"], ["manage_machines", "manage_qr"]].map((actions) => ({ actions })))("withholds identity UI from $actions", ({ actions }) => {
    expect(getStaffAccess(actions, false, false).allowedTabs).not.toContain("devices");
  });
  it("admits MANAGE_DEVICES and superadmin", () => {
    expect(getStaffAccess(["manage_devices"], false, false).allowedTabs).toContain("devices");
    expect(getStaffAccess(["manage_devices"], false, false).allowedTabs).toContain("emailtemplates");
    expect(getStaffAccess([], true, false).allowedTabs).toContain("devices");
    expect(TAB_LABELS.devices).toBe("Devices");
    expect(TAB_GROUPS.find((g) => g.label === "Machines")?.tabs).toContain("devices");
  });
  it("is module gated and has stable scoped/unscoped routes", () => {
    expect(filterTabsByEnabledModules(["devices"], { enabled_modules: [] })).toEqual([]);
    expect(filterTabsByEnabledModules(["devices"], { enabled_modules: ["devices"] })).toEqual(["devices"]);
    expect(staffTabPath("devices", false)).toBe("/admin/devices");
    expect(tabFromStaffPath("/m/forge/admin/devices", false)).toBe("devices");
  });
});
