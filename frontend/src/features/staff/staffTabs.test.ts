import { describe, expect, it } from "vitest";
import { TAB_LABELS } from "./staffAccess";
import { filterTabsByEnabledModules, staffPathState, tabFromStaffPath } from "./staffTabs";

describe("staff printing route alias", () => {
  it("maps the legacy deep link to Machines", () => {
    expect(tabFromStaffPath("/admin/printing", false)).toBe("machines");
    expect(staffPathState("/m/forge/admin/printing", false)).toEqual({ makerspaceSlug: "forge", tab: "machines" });
  });

  it("uses a generic label for the multi-integration platform tab", () => {
    expect(TAB_LABELS.platform).toBe("Platform settings");
  });
});

describe("tombstoned apps", () => {
  const space = { id: 1, name: "Forge", enabled_modules: ["staff_admin", "reports"] };

  it("keeps the warranty tab when the deployment ships the app", () => {
    expect(filterTabsByEnabledModules(["warranty", "reports"], space)).toEqual(["warranty", "reports"]);
  });

  it("hides the warranty tab when the app is tombstoned", () => {
    // warranty is gated by core staff_admin, so no module key can express this --
    // without unavailable_apps the tab would render and 404 on every request.
    const tombstoned = { ...space, unavailable_apps: ["warranty"] };
    expect(filterTabsByEnabledModules(["warranty", "reports"], tombstoned)).toEqual(["reports"]);
  });

  it("hides it even before the makerspace's modules have loaded", () => {
    const partial = { id: 1, name: "Forge", unavailable_apps: ["warranty"] };
    expect(filterTabsByEnabledModules(["warranty", "reports"], partial)).toEqual(["reports"]);
  });
});
