const ALL_TABS = [
  "dashboard", "notifications", "requests", "direct", "handover", "inventory", "needsfix", "categories", "machines", "events", "organized", "bookings", "members", "tobuy", "transfers",
  "stocktake", "containers", "ledger", "reports", "accountability", "warranty", "bulk", "qr", "scanner", "api", "settings", "emailtemplates", "users", "platform", "audit",
  "email-logs", "payments", "organization-analytics", "modules", "exports", "backups", "migration",
] as const;

export const STAFF_TAB_KEYS: readonly string[] = ALL_TABS;

export const TAB_LABELS: Record<string, string> = {
  dashboard: "Dashboard",
  notifications: "Notifications",
  requests: "Requests",
  direct: "Direct handout",
  handover: "Job handover",
  ledger: "Ledger",
  inventory: "Inventory",
  categories: "Categories",
  needsfix: "To-be-fixed",
  stocktake: "Stocktake",
  transfers: "Transfers",
  containers: "Containers",
  bulk: "Bulk import",
  qr: "QR Tools",
  scanner: "Scanner",
  machines: "Machines",
  events: "Events",
  organized: "Organized events",
  bookings: "Bookings",
  members: "Members",
  tobuy: "To Buy",
  reports: "Reports",
  "organization-analytics": "Organization analytics",
  accountability: "Accountability",
  warranty: "Warranties",
  audit: "Audit log",
  users: "Users",
  settings: "Settings",
  emailtemplates: "Email templates",
  "email-logs": "Email log",
  api: "API access",
  platform: "Platform settings",
  payments: "Payments",
  modules: "Modules",
  exports: "Data export",
  backups: "Backup & restore",
  migration: "Tenant migration",
};

export const TAB_GROUPS: { label: string; tabs: string[] }[] = [
  { label: "Operate", tabs: ["dashboard", "notifications", "requests", "direct", "handover", "payments", "ledger", "transfers", "stocktake", "tobuy"] },
  { label: "Inventory", tabs: ["inventory", "categories", "needsfix", "containers", "bulk", "qr", "scanner"] },
  { label: "Machines", tabs: ["machines"] },
  { label: "Events", tabs: ["events", "organized"] },
  { label: "Bookings", tabs: ["bookings"] },
  { label: "Members", tabs: ["members"] },
  { label: "Insights", tabs: ["reports", "organization-analytics", "accountability", "warranty", "audit"] },
  { label: "Admin", tabs: ["users", "settings", "emailtemplates", "email-logs", "api", "exports", "backups", "migration", "modules", "platform"] },
];

// Permissions only. Module availability is decided in exactly one place --
// `filterTabsByEnabledModules` in staffTabs.ts -- because two maps naming the same tab
// is how a tab ends up gated in the sidebar but not on the route, or vice versa.
/**
 * `isMachineOnly` is SERVER-derived (`is_machine_only` on the membership) and must not be
 * re-derived from `actions`: a null-`assigned_role` legacy membership is scope-exempt and
 * cannot be expressed here, and holding `manage_machines` is a different question from
 * being narrowed by machine scope. The backend refuses the notification inbox for exactly
 * this actor, so a locally-guessed value would render a tab that 403s on every request.
 */
export function getStaffAccess(
  actions: readonly string[],
  isSuperadmin: boolean,
  singleTenantLocked: boolean,
  isMachineOnly = false,
) {
  const has = (action: string) => isSuperadmin || actions.includes(action);
  const canEditInventory = has("edit_inventory");
  const canViewInventory = has("view_inventory");
  const canSeePrinting = has("manage_printing") || has("manage_machines");
  const canManageMachines = has("manage_machines");
  const canManageEvents = has("manage_events");
  const canManageBookings = has("manage_bookings");
  const canViewAudit = has("view_audit");
  const canManageQr = has("manage_qr");
  const canManageMakerspace = has("manage_makerspace");
  const canIssueDirectLoan = has("issue_direct_loan");
  const canSeeHardware = isSuperadmin || ["accept_request", "reject_request", "assign_box", "issue_request", "issue_direct_loan", "return_request"].some((action) => actions.includes(action));
  const canUseToBuy = has("edit_inventory") || has("manage_printing") || has("manage_machines") || has("manage_makerspace");
  const canChooseToBuyKind = has("manage_makerspace");
  const canSeeDashboard = has("view_inventory") || has("manage_printing") || has("manage_machines") || has("manage_makerspace");
  // Mirrors rbac.HANDOUT_ACTIONS / _HANDOUT_MUTATIONS. `collect_service_request` belongs
  // here so a front-desk role that also hands over finished machine jobs still reads as
  // handover-only and keeps the narrow tab set, rather than being shown the whole console.
  const HANDOUT = ["view_inventory", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "collect_service_request"];
  const HANDOUT_MUTATIONS = ["assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "collect_service_request"];
  const handoutOnly = !isSuperadmin && actions.length > 0 && actions.every((action) => HANDOUT.includes(action)) && actions.some((action) => HANDOUT_MUTATIONS.includes(action));
  // Mirrors the backend IMPLIED_ACTIONS edge: managing machines includes handing their
  // finished work over, so a manager needs no separate grant.
  const canCollectServiceRequests = has("collect_service_request") || canManageMachines;
  const printingOnly = canSeePrinting && !canEditInventory && !canManageMakerspace;
  const baseTabs = handoutOnly ? (["requests", "direct", "handover"] as const) : ALL_TABS;
  const allowedTabs: readonly string[] = baseTabs.filter((tabName) => {
    if (tabName === "dashboard") return !handoutOnly && (isSuperadmin || canSeeDashboard);
    // The inbox has no machine provenance and its read state is makerspace-wide, so the
    // backend withholds it from a per-type maintainer entirely. Omit the tab rather than
    // render one that 403s — the same reason a tombstoned app's sidebar entry is dropped.
    if (tabName === "notifications") return !handoutOnly && !isMachineOnly;
    if (tabName === "tobuy") return canUseToBuy;
    if (tabName === "needsfix") return canEditInventory;
    if (tabName === "categories") return canEditInventory;
    if (tabName === "bulk") return canEditInventory;
    if (tabName === "stocktake") return canEditInventory;
    if (tabName === "direct") return canIssueDirectLoan;
    if (tabName === "handover") return canCollectServiceRequests;
    if (tabName === "inventory") return canViewInventory;
    if (tabName === "ledger") return canViewInventory;
    if (tabName === "transfers") return canEditInventory || isSuperadmin;
    if (tabName === "containers") return canManageQr;
    if (tabName === "qr") return canManageQr;
    if (tabName === "scanner") return canManageQr;
    if (tabName === "audit") return canViewAudit;
    if (tabName === "accountability") return canViewAudit;
    if (tabName === "reports") return canViewAudit || canSeePrinting || canManageMachines;
    if (tabName === "warranty") return canEditInventory || canSeePrinting;
    if (tabName === "users") return canManageMakerspace;
    if (tabName === "settings") return canManageMakerspace;
    if (tabName === "emailtemplates") return canEditInventory || canSeePrinting;
    if (tabName === "email-logs") return canManageMakerspace;
    if (tabName === "platform") return isSuperadmin && !singleTenantLocked;
    // Superadmin-only, matching the backend: `enabled_modules` is superadmin-owned and a
    // staff PATCH carrying it is a hard 403. Unlike `platform` this IS available in a
    // single-tenant deployment -- that operator is exactly who needs to install modules.
    if (tabName === "modules") return isSuperadmin;
    if (tabName === "machines") return canManageMachines;
    if (tabName === "events") return canManageEvents;
    // Organizer authority is per event and cross-venue; selected-space actions cannot
    // describe it. Superadmins are excluded because the organizer endpoint excludes them.
    // Excluded in a single-tenant deployment too: the organizer list is a TARGETLESS global
    // route, and origin_scope._global_endpoint_allowed permits only `admin-makerspaces` on a
    // hard-scoped staff origin, so on a verified custom domain the tab would render and then
    // 403 on every load. Those users reach it through the central console instead.
    if (tabName === "organized") return !isSuperadmin && !singleTenantLocked;
    // Like organized events, organization analytics is targetless and cross-makerspace.
    // A hard-scoped tenant origin rejects it before application authorization runs.
    if (tabName === "organization-analytics") return !isSuperadmin && !singleTenantLocked;
    if (tabName === "bookings") return canManageBookings;
    if (tabName === "members") return canManageMakerspace;
    if (tabName === "payments") return canManageMakerspace;
    if (tabName === "exports") return canManageMakerspace;
    if (tabName === "backups") return canManageMakerspace;
    if (tabName === "migration") return isSuperadmin;
    if (tabName === "requests") return canSeeHardware;
    return true;
  });
  return {
    handoutOnly,
    printingOnly,
    canSeeHardware,
    canSeePrinting,
    canUseToBuy,
    canEditInventory,
    canViewInventory,
    canIssueDirectLoan,
    canViewAudit,
    canManageQr,
    canManageMakerspace,
    canManageMachines,
    canManageEvents,
    canManageBookings,
    canCollectServiceRequests,
    canChooseToBuyKind,
    allowedTabs,
    // A handover-only staffer lands on Requests when they have it -- but a collect-only
    // role does not, and defaulting to a tab they cannot open would open the console on an
    // error. Fall through to whatever they actually have.
    defaultTab: handoutOnly
      ? (allowedTabs.includes("requests") ? "requests" : (allowedTabs[0] ?? "handover"))
      : (allowedTabs.includes("dashboard") ? "dashboard" : (allowedTabs[0] ?? "dashboard")),
  };
}
