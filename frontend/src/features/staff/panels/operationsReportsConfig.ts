export type ReportCatalogItem = {
  key: string; title: string; fields: string[]; exportable: boolean; summary: boolean;
  required_modules: string[]; available: boolean | null; unavailable_reason: string | null;
  grains: string[]; chart_hint: string; aggregate_supported: boolean;
};
export type ReportCatalog = { results: ReportCatalogItem[] };
export type ReportKey = string;

// The organization endpoint aggregates one report across a whole organization, and only
// these keys have an aggregation strategy on the server (STRATEGIES in
// apps/operations/org_report_strategies.py). Every other key is per-makerspace only —
// offering one for an organization would call the endpoint with a key it rejects.
const aggregateSupportedKeys = new Set([
  "summary", "taken-items", "active-loans", "returns", "damaged-missing",
  "damaged-lost", "qr-scans", "recently-added", "machine-usage", "most-lent",
  "top-borrowers", "member-activity", "event-attendance", "booking-utilization",
  "maintenance-activity", "fablab-health", "payment-reconciliation",
  "evidence-compliance",
]);

export const reportDefinitions: ReportCatalogItem[] = [
  "summary", "taken-items", "active-loans", "returns", "damaged-missing",
  "damaged-lost", "qr-scans", "most-lent", "top-borrowers", "recently-added",
  "machine-usage", "event-attendance", "booking-utilization", "maintenance-activity",
  "member-activity", "machine-service", "printer-service", "fablab-health",
  "payment-reconciliation", "loan-throughput", "inventory-control",
  "evidence-compliance", "import-quality", "procurement-performance",
  "communications-health", "community-engagement", "module-operational-health",
].map((key) => ({
  key, title: key.replace(/-/g, " ").replace(/^./, (letter) => letter.toUpperCase()),
  fields: [], exportable: key !== "summary", summary: key === "summary",
  required_modules: [], available: true, unavailable_reason: null,
  grains: ["day"], chart_hint: "table",
  aggregate_supported: aggregateSupportedKeys.has(key),
}));

export type SavedReportView = {
  id: string; name: string; startDate: string; endDate: string;
  scope: "all" | `makerspace:${number}`; scopeLabel: string; selectedReport: ReportKey;
};

export const savedViewsStorageKey = "operations-reports-saved-views-v1";

export function reportTitle(key: ReportKey, definitions = reportDefinitions) {
  return definitions.find((report) => report.key === key)?.title ?? key;
}

export function newSavedViewId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function loadSavedReportViews(): SavedReportView[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(savedViewsStorageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((view): view is SavedReportView => Boolean(
      view && typeof view.id === "string" && typeof view.name === "string" &&
      typeof view.startDate === "string" && typeof view.endDate === "string" &&
      typeof view.scope === "string" && typeof view.scopeLabel === "string" &&
      typeof view.selectedReport === "string",
    ));
  } catch {
    return [];
  }
}
