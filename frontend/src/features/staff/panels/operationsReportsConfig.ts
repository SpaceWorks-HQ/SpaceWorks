export type ReportCatalogItem = {
  key: string; title: string; fields: string[]; exportable: boolean; summary: boolean;
  required_modules: string[]; available: boolean | null; unavailable_reason: string | null;
  grains: string[]; chart_hint: string; aggregate_supported: boolean;
  // Server capabilities (phase 10). Absent on an older server: treat as unrestricted.
  allowed_formats?: Array<"csv" | "xlsx">; schedulable?: boolean; previewable?: boolean;
  condition_metrics?: string[];
};

export function reportFormats(report: Pick<ReportCatalogItem, "allowed_formats">): Array<"csv" | "xlsx"> {
  return report.allowed_formats?.length ? report.allowed_formats : ["csv", "xlsx"];
}

export function reportGrain(report: Pick<ReportCatalogItem, "grains"> | undefined, requested: string): string {
  return report?.grains.includes(requested) ? requested : (report?.grains[0] ?? "day");
}
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
  "certification-coverage",
].map((key) => ({
  key, title: key.replace(/-/g, " ").replace(/^./, (letter) => letter.toUpperCase()),
  fields: [], exportable: key !== "summary", summary: key === "summary",
  required_modules: [], available: true, unavailable_reason: null,
  grains: ["day"], chart_hint: "table",
  aggregate_supported: aggregateSupportedKeys.has(key),
}));

export function reportTitle(key: ReportKey, definitions = reportDefinitions) {
  return definitions.find((report) => report.key === key)?.title ?? key;
}
