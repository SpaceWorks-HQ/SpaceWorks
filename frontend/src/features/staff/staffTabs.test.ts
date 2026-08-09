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
  const access = (actions: string[]) => getStaffAccess(actions, false, false);

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
    // Module availability is filterTabsByEnabledModules' job, not getStaffAccess'.
    const { allowedTabs } = access(["collect_service_request"]);
    const space = { enabled_modules: ["staff_admin"] };

    expect(filterTabsByEnabledModules(allowedTabs, space)).not.toContain("handover");
  });
});

describe("every tab is gated on the module that backs it", () => {
  // A saved makerspace always carries the six core keys, because `_canonical_modules`
  // adds them back on every write -- so "module off" is a non-empty list that omits it.
  const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];
  const tabsFor = (modules: string[]) =>
    filterTabsByEnabledModules(getStaffAccess([], true, false).allowedTabs, { enabled_modules: modules });

  it.each([
    ["tobuy", "procurement"],
    ["transfers", "stock_transfers"],
    ["stocktake", "stocktake"],
    ["containers", "containers"],
    ["bulk", "bulk_import"],
    ["notifications", "notifications"],
    ["machines", "machines"],
    ["handover", "machine_service"],
    ["events", "events"],
    ["bookings", "bookings"],
    ["reports", "reports"],
  ])("hides %s when %s is uninstalled", (tab, module) => {
    expect(tabsFor([...CORE, module])).toContain(tab);
    expect(tabsFor(CORE)).not.toContain(tab);
  });

  it("gates QR tools on print batches, not on the core key it cannot switch off", () => {
    // Every action in the panel requires a selected batch, so `qr_management` -- which is
    // core and always on -- gated nothing at all.
    expect(tabsFor(CORE)).not.toContain("qr");
    expect(tabsFor([...CORE, "qr_print_batches"])).toContain("qr");
  });

  it("keeps core-backed tabs when every optional module is off", () => {
    const tabs = tabsFor(CORE);

    for (const tab of ["dashboard", "requests", "inventory", "ledger", "scanner", "settings", "users", "audit"]) {
      expect(tabs).toContain(tab);
    }
  });

  it("keeps members and the email log ungated", () => {
    const tabs = tabsFor(CORE);

    // Gating `members` would take the staff roster and role assignment with it, letting a
    // space lock itself out of its own administration.
    expect(tabs).toContain("members");
    // A module-blocked message becomes a terminal SKIPPED row so the operator can see what
    // the toggle suppressed; gating the log would hide exactly that evidence.
    expect(tabs).toContain("email-logs");
  });

  it("treats an unloaded makerspace as unrestricted rather than blanking the console", () => {
    expect(filterTabsByEnabledModules(getStaffAccess([], true, false).allowedTabs, undefined))
      .toContain("tobuy");
  });
});
