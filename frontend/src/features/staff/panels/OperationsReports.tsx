import { useEffect, useState } from "react";

import { BarChart, DataState, ReportTable, StatCards } from "./OperationsReportsParts";
import { OperationsReportsFablab } from "./OperationsReportsFablab";
import { OperationsReportsHardware } from "./OperationsReportsHardware";
import { OperationsReportsMachineService } from "./OperationsReportsMachineService";
import { OperationsReportsMembers } from "./OperationsReportsMembers";
import { OperationsReportsPayments } from "./OperationsReportsPayments";
import { OperationsReportsFinance } from "./OperationsReportsFinance";
import { OperationsReportsPrinterService } from "./OperationsReportsPrinterService";
import { OperationsReportsCoverage } from "./OperationsReportsCoverage";
import { OperationsReportExports } from "./OperationsReportExports";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import { type ReportCatalog, type ReportKey } from "./operationsReportsConfig";
import { ServerReportViews } from "./ServerReportViews";
import { SelectedReportPreview } from "./SelectedReportPreview";
import type { ReportViewState } from "./reportViewsApi";
import { PAYMENT_STATUSES, PAYMENT_SUBJECTS } from "../paymentsApi";

type Summary = {
  products: number; assets: number; active_loans: number;
  available_quantity: number; issued_quantity: number;
  damaged_quantity: number; missing_quantity: number;
};

export function OperationsReports({
  makerspace,
  makerspaces,
  isSuperadmin,
  printingOnly = false,
  canViewAudit,
  canManageMachines,
  canViewFinance = false,
}: {
  makerspace: Makerspace;
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  printingOnly?: boolean;
  canViewAudit: boolean;
  canManageMachines: boolean;
  canViewFinance?: boolean;
}) {
  const [allMakerspaces, setAllMakerspaces] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [grain, setGrain] = useState("day");
  const [selectedReport, setSelectedReport] = useState<ReportKey>("most-lent");
  const [columns, setColumns] = useState<string[]>([]);
  const [months, setMonths] = useState("");
  const [paymentStatus, setPaymentStatus] = useState("");
  const [paymentSubject, setPaymentSubject] = useState("");
  const aggregate = isSuperadmin && allMakerspaces;
  const scopeKey = aggregate ? "all" : makerspace.id;
  const analyticsBase = aggregate ? "/admin/analytics" : `/admin/makerspace/${makerspace.id}/analytics`;
  const reportsBase = aggregate ? "/admin/reports" : `/admin/makerspace/${makerspace.id}/reports`;
  const dateQuery = [startDate ? `start=${encodeURIComponent(startDate)}` : "", endDate ? `end=${encodeURIComponent(endDate)}` : ""].filter(Boolean).join("&");
  const dateSuffix = dateQuery ? `&${dateQuery}` : "";
  const reportsEnabled = aggregate || (makerspace.enabled_modules ?? []).includes("reports");
  const catalog = useStaffGet<ReportCatalog>(
    ["report-catalog", scopeKey],
    aggregate ? "/admin/reports/catalog" : `/admin/makerspace/${makerspace.id}/reports/catalog`,
    reportsEnabled,
  );
  const catalogEntries = catalog.data?.results ?? [];
  useEffect(() => {
    if (!catalog.data || catalogEntries.some((item) => item.key === selectedReport && item.available !== false)) return;
    const firstAvailable = catalogEntries.find((item) => item.available !== false);
    if (firstAvailable) setSelectedReport(firstAvailable.key);
  }, [catalog.data, catalogEntries, selectedReport]);
  const hardwareEnabled = canViewAudit && reportsEnabled;
  const summary = useStaffGet<Summary>(["operations-report", "summary", scopeKey, startDate, endDate], `${analyticsBase}/summary?${dateQuery}`, hardwareEnabled);

  const scopeLabel = aggregate ? "all makerspaces" : makerspace.name;
  const makerspaceName = (id: number) => makerspaces.find((space) => space.id === id)?.name ?? `#${id}`;
  const availableExports = reportsEnabled ? catalogEntries.filter((report) => report.exportable && report.available !== false) : [];
  const selected = catalogEntries.find((report) => report.key === selectedReport);
  const effectiveGrain = (selected?.grains ?? ["day"]).includes(grain) ? grain : selected?.grains[0] ?? "day";
  const savedState: ReportViewState = {
    report_key: selectedReport, grain: effectiveGrain, columns,
    filters: { ...(startDate ? { start: startDate } : {}), ...(endDate ? { end: endDate } : {}),
      ...(months && selectedReport === "member-retention" ? { months: Number(months) } : {}),
      ...(selectedReport === "payment-reconciliation" && paymentStatus ? { status: paymentStatus } : {}),
      ...(selectedReport === "payment-reconciliation" && paymentSubject ? { subject_type: paymentSubject } : {}) },
  };
  const applyView = (state: ReportViewState) => {
    setStartDate(state.filters.start ?? ""); setEndDate(state.filters.end ?? "");
    setSelectedReport(state.report_key); setGrain(state.grain); setColumns(state.columns);
    setMonths(state.filters.months ? String(state.filters.months) : "");
    setPaymentStatus(state.filters.status ?? ""); setPaymentSubject(state.filters.subject_type ?? "");
  };

  return (
    <div className="space-y-4">
      <Panel title="Reports">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="title-section">
              {printingOnly ? "3D printing reporting" : "Operations reporting"} for {scopeLabel}
            </h3>
            <p className="text-xs text-muted">
              {printingOnly
                ? "Print jobs, printer hours, and filament usage."
                : "Inventory movement, borrower activity, exceptions, and print usage."}
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="eyebrow grid gap-1">
              <span>Start</span>
              <input className="desk-input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </label>
            <label className="eyebrow grid gap-1">
              <span>End</span>
              <input className="desk-input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </label>
            <label className="eyebrow grid gap-1">
              <span>Report</span>
              <select className="desk-input" value={selectedReport} onChange={(event) => { setSelectedReport(event.target.value as ReportKey); setColumns([]); }}>
                {!catalogEntries.length ? <option value={selectedReport}>{catalog.isLoading ? "Loading reports..." : "No reports available"}</option> : null}
                {catalogEntries.map((report) => (
                  <option key={report.key} value={report.key} disabled={report.available === false}>
                    {report.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="eyebrow grid gap-1">
              <span>Grain</span>
              <select className="desk-input" value={effectiveGrain} onChange={(event) => setGrain(event.target.value)}>
                {(selected?.grains ?? ["day"]).map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            {isSuperadmin ? (
              <label className="flex items-center gap-2 pb-2 text-sm text-ink">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-current"
                  checked={allMakerspaces}
                  onChange={(event) => setAllMakerspaces(event.target.checked)}
                />
                All makerspaces
              </label>
            ) : null}
          </div>
        </div>
        {catalog.error ? <p className="mt-3 text-sm text-danger">{catalog.error instanceof Error ? catalog.error.message : "Could not load report catalog."}</p> : null}
        {selectedReport === "member-retention" ? <label className="eyebrow grid gap-1 mt-3">Retention months (blank: 3, 6, 12)<input className="desk-input" type="number" min={1} max={120} value={months} onChange={(event) => setMonths(event.target.value)} /></label> : null}
        {selectedReport === "payment-reconciliation" ? <div className="flex flex-wrap gap-2 mt-3">
          <label className="eyebrow grid gap-1">Report payment status<select className="desk-input" value={paymentStatus} onChange={(event) => setPaymentStatus(event.target.value)}><option value="">All statuses</option>{PAYMENT_STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="eyebrow grid gap-1">Report charge type<select className="desk-input" value={paymentSubject} onChange={(event) => setPaymentSubject(event.target.value)}><option value="">All types</option>{PAYMENT_SUBJECTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div> : null}
        {!aggregate && reportsEnabled && (makerspace.enabled_features ?? []).includes("reports.saved_views") ?
          <ServerReportViews key={makerspace.id} makerspaceId={makerspace.id} state={savedState} fields={selected?.fields ?? []} onColumns={setColumns} onApply={applyView} /> : null}
        {!printingOnly && hardwareEnabled ? (
          <DataState loading={summary.isLoading} error={summary.error} empty={!summary.data}>
            <StatCards
              stats={[
                ["Products", summary.data?.products],
                ["Assets", summary.data?.assets],
                ["Active loans", summary.data?.active_loans],
                ["Available", summary.data?.available_quantity],
                ["Issued", summary.data?.issued_quantity],
                ["Damaged", summary.data?.damaged_quantity],
                ["Missing", summary.data?.missing_quantity],
              ]}
            />
            <div className="mt-4">
              <BarChart rows={[
                { label: "Available", value: summary.data?.available_quantity ?? 0 },
                { label: "Issued", value: summary.data?.issued_quantity ?? 0 },
                { label: "Damaged", value: summary.data?.damaged_quantity ?? 0 },
                { label: "Missing", value: summary.data?.missing_quantity ?? 0 },
              ]} valueLabel="units" />
            </div>
            <ReportTable data={{ rows: [
              ["metric", "value"],
              ["products", summary.data?.products ?? 0],
              ["assets", summary.data?.assets ?? 0],
              ["active_loans", summary.data?.active_loans ?? 0],
              ["available_quantity", summary.data?.available_quantity ?? 0],
              ["issued_quantity", summary.data?.issued_quantity ?? 0],
              ["damaged_quantity", summary.data?.damaged_quantity ?? 0],
              ["missing_quantity", summary.data?.missing_quantity ?? 0],
            ] }} />
          </DataState>
        ) : !printingOnly && !reportsEnabled ? <p className="mt-3 text-sm text-muted">Module disabled</p> : null}
      </Panel>

      {!printingOnly ? (
      <>
      <OperationsReportExports
        reports={availableExports}
        selectedReport={selectedReport}
        onSelect={(key) => { setSelectedReport(key); setColumns([]); }}
        reportsBase={reportsBase}
        dateSuffix={dateSuffix}
        filters={{ months, status: paymentStatus, subject_type: paymentSubject }}
        grain={effectiveGrain}
        aggregate={aggregate}
        makerspaceId={makerspace.id}
        reportsEnabled={reportsEnabled}
      />

      <SelectedReportPreview report={selected} analyticsBase={analyticsBase} scopeKey={scopeKey} start={startDate} end={endDate} grain={effectiveGrain} columns={columns} months={months} filters={savedState.filters} />
      <OperationsReportsHardware analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} enabled={hardwareEnabled} aggregate={aggregate} makerspaceName={makerspaceName} />
      {canViewFinance || isSuperadmin ? <OperationsReportsFinance catalog={catalogEntries} analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} grain={grain} aggregate={aggregate} makerspaceName={makerspaceName} /> : null}
      <OperationsReportsCoverage catalog={catalogEntries} analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} grain={grain} aggregate={aggregate} makerspaceName={makerspaceName} />
      <OperationsReportsMembers makerspaceId={makerspace.id} aggregate={aggregate} startDate={startDate} endDate={endDate} enabled={hardwareEnabled} />
      {canViewFinance || isSuperadmin ? <OperationsReportsPayments analyticsBase={analyticsBase} scopeKey={scopeKey} startDate={startDate} endDate={endDate} enabled={reportsEnabled} makerspaceName={makerspaceName} /> : null}
      </>
      ) : null}

      {!printingOnly ? <OperationsReportsFablab makerspace={makerspace} aggregate={aggregate} canViewAudit={canViewAudit} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} /> : null}

      <OperationsReportsPrinterService makerspace={makerspace} aggregate={aggregate} canManageMachines={canManageMachines} reportsEnabled={reportsEnabled} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} />
      <OperationsReportsMachineService makerspace={makerspace} aggregate={aggregate} canManageMachines={canManageMachines} reportsEnabled={reportsEnabled} startDate={startDate} endDate={endDate} makerspaceName={makerspaceName} />
    </div>
  );
}
