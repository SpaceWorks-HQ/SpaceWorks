import { DataState, ReportTable, type ReportRows } from "./OperationsReportsParts";
import { Panel, useStaffGet } from "./shared";
import type { ReportCatalogItem } from "./operationsReportsConfig";
import type { ReportViewState } from "./reportViewsApi";

export function SelectedReportPreview({ report, analyticsBase, scopeKey, start, end, grain, columns, months, filters }: {
  report?: ReportCatalogItem; analyticsBase: string; scopeKey: string | number;
  start: string; end: string; grain: string; columns: string[]; months: string;
  filters?: ReportViewState["filters"];
}) {
  const params = new URLSearchParams({ grain: (report?.grains ?? ["day"]).includes(grain) ? grain : report?.grains[0] ?? "day" });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (months && report?.key === "member-retention") params.set("months", months);
  if (report?.key === "payment-reconciliation") {
    if (filters?.status) params.set("status", filters.status);
    if (filters?.subject_type) params.set("subject_type", filters.subject_type);
  }
  const result = useStaffGet<ReportRows & { meta?: { definition?: string; limitations?: string } }>(
    ["selected-report", scopeKey, report?.key, start, end, grain, months, filters],
    `${analyticsBase}/${report?.key}?${params}`, Boolean(report && report.available !== false && report.previewable !== false && !report.summary),
  );
  if (!report || report.summary || report.previewable === false) return null;
  const rows = result.data?.rows ?? [];
  const indexes = columns.length && rows[0] ? columns.map((column) => rows[0].indexOf(column)).filter((index) => index >= 0) : [];
  const visible = indexes.length ? { rows: rows.map((row) => indexes.map((index) => row[index])) } : result.data;
  return <Panel title={`${report.title} preview`}>
    <DataState loading={result.isLoading} error={result.error} empty={rows.length <= 1}>
      <ReportTable data={visible} />
    </DataState>
    {result.data?.meta?.definition ? <p className="mt-2 text-xs text-muted">{result.data.meta.definition}</p> : null}
    {result.data?.meta?.limitations ? <p className="mt-2 text-xs text-muted">{result.data.meta.limitations}</p> : null}
  </Panel>;
}
