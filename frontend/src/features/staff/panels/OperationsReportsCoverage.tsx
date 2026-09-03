import {
  BarChart, DataState, LineChart, PerMakerspaceTables, ReportTable, StackedBarChart,
  chartRows, reportRows, typedRows, type ReportRows,
} from "./OperationsReportsParts";
import type { ReportCatalogItem } from "./operationsReportsConfig";
import { Panel, useStaffGet } from "./shared";

const COVERAGE_KEYS = new Set([
  "loan-throughput", "inventory-control", "evidence-compliance", "import-quality",
  "procurement-performance", "communications-health", "community-engagement",
  "module-operational-health",
]);
const CHART_FIELDS: Record<string, [string, string, string]> = {
  "loan-throughput": ["period", "request_count", "requests"],
  "inventory-control": ["module_key", "quantity", "units"],
  "evidence-compliance": ["period", "created_count", "evidence"],
  "import-quality": ["period", "processed_rows", "rows"],
  "procurement-performance": ["period", "units", "units"],
  "communications-health": ["channel", "delivery_count", "deliveries"],
  "community-engagement": ["module_key", "active_accounts", "accounts"],
  "module-operational-health": ["module_key", "activity_count", "actions"],
};
const STACKED_FIELDS: Record<string, [string, string, string, string]> = {
  "loan-throughput": ["period", "request_status", "request_count", "requests"],
  "import-quality": ["period", "status", "processed_rows", "rows"],
  "procurement-performance": ["period", "status", "units", "units"],
  "communications-health": ["channel", "status", "delivery_count", "deliveries"],
};

export function OperationsReportsCoverage({ catalog, analyticsBase, scopeKey, startDate, endDate, grain, aggregate, makerspaceName }: {
  catalog: ReportCatalogItem[]; analyticsBase: string; scopeKey: string | number;
  startDate: string; endDate: string; grain: string; aggregate: boolean;
  makerspaceName: (id: number) => string;
}) {
  return <section className="grid gap-4 xl:grid-cols-2" aria-label="Module coverage reports">{catalog.filter((report) => COVERAGE_KEYS.has(report.key)).map((report) => <CoverageReport key={report.key} report={report} analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} grain={grain} aggregate={aggregate} makerspaceName={makerspaceName} />)}</section>;
}

function CoverageReport({ report, analyticsBase, scopeKey, startDate, endDate, grain, aggregate, makerspaceName }: {
  report: ReportCatalogItem; analyticsBase: string; scopeKey: string | number;
  startDate: string; endDate: string; grain: string; aggregate: boolean;
  makerspaceName: (id: number) => string;
}) {
  const params = new URLSearchParams({ limit: "100", grain });
  if (startDate) params.set("start", startDate);
  if (endDate) params.set("end", endDate);
  const enabled = report.available !== false;
  const result = useStaffGet<ReportRows>(["operations-report", report.key, scopeKey, startDate, endDate, grain], `${analyticsBase}/${report.key}?${params.toString()}`, enabled);
  const [labelKey, valueKey, valueLabel] = CHART_FIELDS[report.key];
  const Chart = report.chart_hint.includes("line") ? LineChart : BarChart;
  const stacked = STACKED_FIELDS[report.key];
  return (
    <Panel title={report.title}>
      {!enabled ? <p className="text-sm text-muted">{report.unavailable_reason ?? "Module disabled"}</p> : (
        <DataState loading={result.isLoading} error={result.error} empty={!reportRows(result.data).length}>
          {aggregate ? <PerMakerspaceTables data={result.data} nameOf={makerspaceName} /> : <>{stacked ? <StackedBarChart rows={stackedChartRows(result.data, ...stacked.slice(0, 3) as [string, string, string])} valueLabel={stacked[3]} /> : <Chart rows={chartRows(result.data, labelKey, valueKey)} valueLabel={valueLabel} />}<ReportTable data={result.data} /></>}
          {result.data?.meta ? <p className="mt-2 text-xs text-muted">Source: {result.data.meta.source ?? "live"} / {result.data.meta.grain ?? grain}</p> : null}
        </DataState>
      )}
    </Panel>
  );
}

function stackedChartRows(data: ReportRows | undefined, labelKey: string, segmentKey: string, valueKey: string) {
  const groups = new Map<string, Map<string, number>>();
  for (const row of typedRows(data)) {
    const label = String(row[labelKey] ?? "Unknown");
    const segment = String(row[segmentKey] ?? "Unknown");
    const values = groups.get(label) ?? new Map<string, number>();
    values.set(segment, (values.get(segment) ?? 0) + Number(row[valueKey] ?? 0));
    groups.set(label, values);
  }
  return [...groups].map(([label, values]) => ({
    label,
    segments: [...values].map(([segment, value]) => ({ label: segment, value })),
  }));
}
