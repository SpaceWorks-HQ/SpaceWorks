import { describe, expect, it } from "vitest";
import { getStaffAccess, TAB_LABELS } from "./staffAccess";
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

describe("job handover", () => {
  const space = { enabled_modules: ["machine_service", "machines"] };
  const access = (actions: string[]) =>
    getStaffAccess(actions, false, false, space.enabled_modules);

  it("gives a collect-only role the handover tab and nothing else", () => {
    const { allowedTabs, handoutOnly, defaultTab } = access(["collect_service_request"]);

    expect(allowedTabs).toEqual(["handover"]);
    // Still handover-only, so the console stays narrow rather than opening up.
    expect(handoutOnly).toBe(true);
    // Not "requests": a collect-only role cannot open it, and defaulting there would
    // land them on a tab that is not in their own allowed list.
    expect(defaultTab).toBe("handover");
  });

  it("keeps a hardware handover role on requests while adding handover", () => {
    const { allowedTabs, defaultTab } = access([
      "view_inventory", "issue_request", "issue_direct_loan", "return_request",
      "upload_evidence", "collect_service_request",
    ]);

    expect(allowedTabs).toContain("handover");
    expect(allowedTabs).toContain("requests");
    expect(defaultTab).toBe("requests");
  });

  it("gives a machine manager the tab without granting the action explicitly", () => {
    // Mirrors the backend IMPLIED_ACTIONS edge; a manager who lost the tab would be a
    // regression, since collecting is what they do today.
    expect(access(["manage_machines"]).allowedTabs).toContain("handover");
  });

  it("hides the tab when the deployment does not run machine service", () => {
    expect(getStaffAccess(["collect_service_request"], false, false, []).allowedTabs)
      .not.toContain("handover");
  });
});
