import type { ReactNode } from "react";

import { BarChart, DataState, LineChart, PerMakerspaceTables, PieChart, ReportTable, StackedBarChart, chartRows, reportRows, type ReportRows } from "./OperationsReportsParts";
import { Panel, useStaffGet } from "./shared";

function useHardwareReport(key: string, analyticsBase: string, scopeKey: string | number, startDate: string, endDate: string, enabled: boolean) {
  const dateQuery = [startDate && `start=${encodeURIComponent(startDate)}`, endDate && `end=${encodeURIComponent(endDate)}`].filter(Boolean).join("&");
  const path = `${analyticsBase}/${key}?limit=100${dateQuery ? `&${dateQuery}` : ""}`;
  return useStaffGet<ReportRows>(["operations-report", key, scopeKey, startDate, endDate], path, enabled);
}

export function OperationsReportsHardware({
  analyticsBase, scopeKey, startDate, endDate, enabled, aggregate, makerspaceName,
}: {
  analyticsBase: string;
  scopeKey: string | number;
  startDate: string;
  endDate: string;
  enabled: boolean;
  aggregate: boolean;
  makerspaceName: (id: number) => string;
}) {
  const mostLent = useHardwareReport("most-lent", analyticsBase, scopeKey, startDate, endDate, enabled);
  const topBorrowers = useHardwareReport("top-borrowers", analyticsBase, scopeKey, startDate, endDate, enabled);
  const damagedMissing = useHardwareReport("damaged-missing", analyticsBase, scopeKey, startDate, endDate, enabled);
  const damagedLost = useHardwareReport("damaged-lost", analyticsBase, scopeKey, startDate, endDate, enabled);
  const recentlyAdded = useHardwareReport("recently-added", analyticsBase, scopeKey, startDate, endDate, enabled);
  const takenItems = useHardwareReport("taken-items", analyticsBase, scopeKey, startDate, endDate, enabled);
  const activeLoans = useHardwareReport("active-loans", analyticsBase, scopeKey, startDate, endDate, enabled);
  const returns = useHardwareReport("returns", analyticsBase, scopeKey, startDate, endDate, enabled);
  const qrScans = useHardwareReport("qr-scans", analyticsBase, scopeKey, startDate, endDate, enabled);
  return (
    <>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Most lent"><DataState loading={mostLent.isLoading} error={mostLent.error} empty={!reportRows(mostLent.data).length}>{aggregate ? <PerMakerspaceTables data={mostLent.data} nameOf={makerspaceName} /> : <><BarChart rows={chartRows(mostLent.data, "product_name", "times_lent")} valueLabel="loans" /><ReportTable data={mostLent.data} /></>}</DataState></Panel>
        <Panel title="Top borrowers"><DataState loading={topBorrowers.isLoading} error={topBorrowers.error} empty={!reportRows(topBorrowers.data).length}>{aggregate ? <PerMakerspaceTables data={topBorrowers.data} nameOf={makerspaceName} /> : <><BarChart rows={chartRows(topBorrowers.data, "holder", "requests")} valueLabel="requests" /><ReportTable data={topBorrowers.data} /></>}</DataState></Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <ReportPanel title="Damaged / missing" query={damagedMissing} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <StackedBarChart rows={stackedRows(data, "product", [["Damaged", "damaged_quantity"], ["Missing", "missing_quantity"]])} valueLabel="units" />} />
        <ReportPanel title="Damaged / lost" query={damagedLost} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <StackedBarChart rows={stackedRows(data, "product_name", [["Damaged", "damaged_quantity"], ["Lost", "lost_quantity"]])} valueLabel="units" />} />
        <ReportPanel title="Recently added" query={recentlyAdded} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <LineChart rows={chartRows(data, "created_at", "total_quantity").reverse()} valueLabel="units" />} />
        <ReportPanel title="Taken items" query={takenItems} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <BarChart rows={chartRows(data, "product", "issued_quantity")} valueLabel="issued" />} />
        <ReportPanel title="Active loans" query={activeLoans} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <StackedBarChart rows={datedCategories(data, "issued_at", "status")} valueLabel="loans" />} />
        <ReportPanel title="Returns" query={returns} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <StackedBarChart rows={datedCategories(data, "closed_at", "status")} valueLabel="returns" />} />
        <ReportPanel title="QR scans" query={qrScans} aggregate={aggregate} makerspaceName={makerspaceName} chart={(data) => <PieChart rows={chartRows(data, "context", "count")} valueLabel="scans" />} />
      </div>
    </>
  );
}

function ReportPanel({ title, query, aggregate, makerspaceName, chart }: {
  title: string; query: { isLoading: boolean; error: unknown; data?: ReportRows };
  aggregate: boolean; makerspaceName: (id: number) => string; chart: (data?: ReportRows) => ReactNode;
}) {
  return <Panel title={title}><DataState loading={query.isLoading} error={query.error} empty={!reportRows(query.data).length}>{aggregate ? <PerMakerspaceTables data={query.data} nameOf={makerspaceName} /> : <>{chart(query.data)}<ReportTable data={query.data} /></>}</DataState></Panel>;
}

function valueAt(data: ReportRows | undefined, row: (string | number | boolean | null)[], key: string) {
  return row[(data?.rows?.[0] ?? []).indexOf(key)];
}

function datedCategories(data: ReportRows | undefined, dateKey: string, categoryKey: string) {
  const counts = new Map<string, Map<string, number>>();
  for (const row of reportRows(data)) {
    const rawDate = String(valueAt(data, row, dateKey) ?? "Unknown");
    const date = rawDate.slice(0, 10);
    const category = String(valueAt(data, row, categoryKey) ?? "Unknown");
    const values = counts.get(date) ?? new Map<string, number>();
    values.set(category, (values.get(category) ?? 0) + 1);
    counts.set(date, values);
  }
  return [...counts].sort(([left], [right]) => left.localeCompare(right)).map(([label, values]) => ({
    label, segments: [...values].map(([segment, value]) => ({ label: segment, value })),
  }));
}

function stackedRows(data: ReportRows | undefined, labelKey: string, segments: [string, string][]) {
  return reportRows(data).map((row) => ({
    label: String(valueAt(data, row, labelKey) ?? "Unknown"),
    segments: segments.map(([label, key]) => ({ label, value: Number(valueAt(data, row, key) ?? 0) })),
  }));
}
