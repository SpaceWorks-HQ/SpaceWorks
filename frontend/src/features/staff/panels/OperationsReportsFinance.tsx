import { DataState, LineChart, PerMakerspaceTables, ReportTable, typedRows, type ReportRows } from "./OperationsReportsParts";
import { reportGrain, type ReportCatalogItem } from "./operationsReportsConfig";
import { Panel, useStaffGet } from "./shared";

const FINANCE_KEYS = new Set(["payments-ledger", "revenue-over-time", "cash-book", "accounting-journal"]);

export function OperationsReportsFinance(props: {
  catalog: ReportCatalogItem[]; analyticsBase: string; scopeKey: number | "all";
  startDate: string; endDate: string; grain: string; aggregate: boolean;
  makerspaceName: (id: number) => string;
}) {
  return <section className="grid gap-4 xl:grid-cols-2" aria-label="Financial reports">
    {props.catalog.filter(report => FINANCE_KEYS.has(report.key)).map(report => <FinanceReport key={report.key} {...props} report={report} />)}
  </section>;
}

function FinanceReport({ report, ...props }: Parameters<typeof OperationsReportsFinance>[0] & { report: ReportCatalogItem }) {
  const grain = reportGrain(report, props.grain);
  const query = new URLSearchParams({ grain });
  if (props.startDate) query.set("start", props.startDate);
  if (props.endDate) query.set("end", props.endDate);
  const result = useStaffGet<ReportRows>(["operations-report", report.key, props.scopeKey, props.startDate, props.endDate, grain],
    `${props.analyticsBase}/${report.key}?${query}`, report.available !== false);
  const currencies = [...new Set(typedRows(result.data).map(row => String(row.currency)))];
  return <Panel title={report.title}>
    <DataState loading={result.isLoading} error={result.error} empty={!typedRows(result.data).length}>
      {props.aggregate ? <PerMakerspaceTables data={result.data} nameOf={props.makerspaceName} /> : <>
        {report.key === "revenue-over-time" ? <>
          <p className="text-xs text-muted">Collected and refunded use the money date. Owed is currently pending debt grouped by its creation date. All dates use the space's timezone.</p>
          {currencies.map(currency => <section key={currency} aria-label={`${currency.toUpperCase()} revenue`}>
            <h4 className="eyebrow">{currency.toUpperCase()}</h4>
            {([ ["collected_amount", "Collected"], ["owed_amount", "Owed"], ["refunded_amount", "Refunded"] ] as const).map(([field, label]) => {
              const totals = new Map<string, number>();
              for (const row of typedRows(result.data).filter(row => row.currency === currency)) {
                const period = String(row.period);
                totals.set(period, (totals.get(period) ?? 0) + Number(row[field]));
              }
              return <LineChart key={field} valueLabel={`${label} ${currency.toUpperCase()}`} rows={[...totals].map(([period, value]) => ({ label: period, value }))} />;
            })}
          </section>)}
        </> : null}
        <ReportTable data={result.data} />
      </>}
    </DataState>
  </Panel>;
}
