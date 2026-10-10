import { describe, expect, it } from "vitest";
import { getStaffAccess, TAB_GROUPS, TAB_LABELS } from "./staffAccess";
import {
  filterTabsByEnabledModules,
  keptStaffSubPath,
  machineTypeSegment,
  parseMachineTypeSegment,
  staffPathState,
  staffTabPath,
  tabFromStaffPath,
} from "./staffTabs";

describe("staff printing route alias", () => {
  it("maps the legacy deep link to Machines", () => {
    expect(tabFromStaffPath("/admin/printing", false)).toBe("machines");
    expect(staffPathState("/m/forge/admin/printing", false)).toEqual({ makerspaceSlug: "forge", tab: "machines", subPath: "" });
  });

  it("uses a generic label for the multi-integration platform tab", () => {
    expect(TAB_LABELS.platform).toBe("Platform settings");
  });
});

describe("data export authority", () => {
  it("shows the export tab only to MANAGE_MAKERSPACE", () => {
    expect(getStaffAccess(["manage_makerspace"], false, false).allowedTabs).toContain("exports");
    expect(getStaffAccess(["edit_inventory"], false, false).allowedTabs).not.toContain("exports");
    expect(staffTabPath("exports", false)).toBe("/admin/data-export");
  });
});

describe("organized events", () => {
  const coreModules = [
    "public_inventory", "request_workflow", "staff_admin", "scanner",
    "qr_management", "evidence_uploads",
  ];

  it("maps organized-event routes with and without a makerspace slug", () => {
    expect(staffTabPath("organized", false)).toBe("/admin/organized-events");
    expect(staffTabPath("organized", false, "forge")).toBe("/m/forge/admin/organized-events");
    expect(tabFromStaffPath("/admin/organized-events", false)).toBe("organized");
    expect(tabFromStaffPath("/m/forge/admin/organized-events", false)).toBe("organized");
  });

  it("places the tab immediately after Events in the Events group", () => {
    expect(TAB_GROUPS.find((group) => group.label === "Events")?.tabs)
      .toEqual(["events", "organized"]);
  });

  it("hides the tab from superadmins and handout-only actors", () => {
    expect(getStaffAccess([], true, false).allowedTabs).not.toContain("organized");
    // Single-tenant deployments are excluded too: the organizer list is a targetless global
    // route and origin_scope._global_endpoint_allowed admits only `admin-makerspaces` on a
    // hard-scoped staff origin, so the tab would 403 on every load there.
    expect(getStaffAccess(["view_inventory"], false, true).allowedTabs).not.toContain("organized");
    expect(getStaffAccess(["issue_request", "return_request"], false, false).allowedTabs)
      .not.toContain("organized");
  });

  it("shows the tab without selected-makerspace manage_events", () => {
    expect(getStaffAccess(["view_inventory"], false, false).allowedTabs).toContain("organized");
  });

  it("ignores the selected makerspace's events module switch", () => {
    const tabs = getStaffAccess(["view_inventory"], false, false).allowedTabs;
    const filtered = filterTabsByEnabledModules(tabs, { enabled_modules: coreModules });
    expect(filtered).toContain("organized");
    expect(filtered).not.toContain("events");
  });

  it("hides the tab when the events app is unavailable deployment-wide", () => {
    const tabs = getStaffAccess(["view_inventory"], false, false).allowedTabs;
    expect(filterTabsByEnabledModules(tabs, { unavailable_apps: ["events"] }))
      .not.toContain("organized");
  });
});
describe("tenant migration authority", () => {
  it("omits the tab for every non-superadmin and gives it a stable route", () => {
    expect(getStaffAccess(["manage_makerspace"], false, false).allowedTabs).not.toContain("migration");
    expect(getStaffAccess([], true, false).allowedTabs).toContain("migration");
    expect(staffTabPath("migration", false)).toBe("/admin/tenant-migration");
  });

  it("omits the tab when the tenant_migration app is tombstoned", () => {
    const space = { id: 1, name: "Forge", unavailable_apps: ["tenant_migration"] };
    expect(filterTabsByEnabledModules(["dashboard", "migration"], space)).toEqual(["dashboard"]);
  });
});

describe("machine-type subpaths", () => {
  it("reads the subpath from both the scoped and unscoped route shapes", () => {
    expect(staffPathState("/admin/machines/12-laser", false).subPath).toBe("12-laser");
    expect(staffPathState("/m/forge/admin/machines/12-laser", false)).toEqual({
      makerspaceSlug: "forge", tab: "machines", subPath: "12-laser",
    });
  });

  it("builds a subpath only for tabs that carry one", () => {
    expect(staffTabPath("machines", false, null, false, "12-laser")).toBe("/admin/machines/12-laser");
    expect(staffTabPath("machines", false, "forge", false, "12-laser")).toBe("/m/forge/admin/machines/12-laser");
    // Every other tab still NORMALISES trailing segments away, so a stale deep link lands
    // on the tab rather than 404ing. Relaxing that globally would change how existing
    // bookmarks resolve, so the exception is opt-in.
    expect(staffTabPath("inventory", false, null, false, "12-laser")).toBe("/admin/inventory");
  });

  it("keeps the id authoritative and treats the slug as decoration", () => {
    // Slug uniqueness is only SCOPED, so a makerspace-local type may legally carry a global
    // built-in's slug. Resolving by slug has already served one type's jobs under another.
    expect(parseMachineTypeSegment("12-laser")).toBe(12);
    expect(parseMachineTypeSegment("12-3d_printer")).toBe(12);
    expect(parseMachineTypeSegment("12")).toBe(12);
    expect(machineTypeSegment({ id: 12, slug: "laser" })).toBe("12-laser");
    expect(machineTypeSegment({ id: 12, slug: "" })).toBe("12");
  });

  // THE REGRESSION THIS EXISTS FOR: StaffWorkspace canonicalizes the URL to the active
  // tab's path, so before the subpath was threaded through, `/admin/machines/12-laser` was
  // rewritten to `/admin/machines` on first render and no per-type link could ever survive.
  // The panel's own tests mount a MemoryRouter directly at the deep link and so would stay
  // green with this reverted.
  it("keeps a subpath through canonicalization only for the tab that resolved it", () => {
    expect(keptStaffSubPath("machines", "machines", "12-laser")).toBe("12-laser");
    expect(staffTabPath("machines", false, null, false, keptStaffSubPath("machines", "machines", "12-laser")))
      .toBe("/admin/machines/12-laser");

    // Requested tab was denied or unavailable and the actor is being sent elsewhere: the
    // machine-type segment must not ride along onto a different tab.
    expect(keptStaffSubPath("machines", "dashboard", "12-laser")).toBe("");
    // No route tab at all (a stored tab, or the bare console root).
    expect(keptStaffSubPath("", "machines", "12-laser")).toBe("");
  });

  it("reads a malformed segment as no selection rather than a default type", () => {
    expect(parseMachineTypeSegment("laser")).toBeNull();
    expect(parseMachineTypeSegment("")).toBeNull();
    expect(parseMachineTypeSegment("0-laser")).toBeNull();
    expect(parseMachineTypeSegment("-3")).toBeNull();
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
  const access = (actions: string[]) => getStaffAccess(actions, false, false);

  it("gives a collect-only role handover and their personal inbox", () => {
    const { allowedTabs, handoutOnly, defaultTab } = access(["collect_service_request"]);

    expect(allowedTabs).toEqual(["handover", "notifications"]);
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

  it("admits personal notifications for a server-flagged machine-only role", () => {
    // The badge lives inside that link, so omitting the tab also stops its polling.
    // Read from the server: the flag is the fourth argument, never derived from actions.
    const flagged = getStaffAccess(["manage_machines"], false, false, true);
    const notFlagged = getStaffAccess(["manage_machines"], false, false, false);

    expect(flagged.allowedTabs).toContain("notifications");
    expect(notFlagged.allowedTabs).toContain("notifications");
    // Default is permissive, so a caller that has not loaded the flag yet keeps the tab
    // rather than flickering it away.
    expect(getStaffAccess(["manage_machines"], false, false).allowedTabs)
      .toContain("notifications");
  });

  it("does not show the hardware Requests tab to a machine-only role", () => {
    const machineOnly = access(["manage_machines"]);

    expect(machineOnly.canSeeHardware).toBe(false);
    expect(machineOnly.allowedTabs).not.toContain("requests");
    expect(machineOnly.defaultTab).toBe("dashboard");
  });

  it("hides the tab when the deployment does not run machine service", () => {
    // Module availability is filterTabsByEnabledModules' job, not getStaffAccess'.
    const { allowedTabs } = access(["collect_service_request"]);
    const space = { enabled_modules: ["staff_admin"] };

    expect(filterTabsByEnabledModules(allowedTabs, space)).not.toContain("handover");
  });
});
