import { DataState } from "./OperationsReportsParts";
import { Panel, useStaffGet } from "./shared";

type PaymentReportRow = {
  makerspace_id?: number;
  currency: string;
  subject_type: string;
  status: string;
  payment_count: number;
  amount_total: string;
  outstanding_amount: string;
};

type PaymentReport = { typed_rows: PaymentReportRow[] };

export function OperationsReportsPayments({
  analyticsBase,
  scopeKey,
  startDate,
  endDate,
  enabled,
}: {
  analyticsBase: string;
  scopeKey: number | "all";
  startDate: string;
  endDate: string;
  enabled: boolean;
}) {
  const query = new URLSearchParams();
  if (startDate) query.set("start", startDate);
  if (endDate) query.set("end", endDate);
  const report = useStaffGet<PaymentReport>(
    ["operations-report", "payment-reconciliation", scopeKey, startDate, endDate],
    `${analyticsBase}/payment-reconciliation?${query.toString()}`,
    enabled,
  );

  return (
    <Panel title="Payment reconciliation">
      <p className="mb-3 text-xs text-muted">Private totals are grouped by makerspace, currency, subject, and status. Pending payments remain visible across date ranges.</p>
      <DataState loading={report.isLoading} error={report.error} empty={!report.data?.typed_rows.length}>
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-left text-sm">
            <thead className="eyebrow bg-surface"><tr>
              {scopeKey === "all" ? <th className="px-3 py-2">Makerspace</th> : null}
              <th className="px-3 py-2">Currency</th><th className="px-3 py-2">Subject</th>
              <th className="px-3 py-2">Status</th><th className="px-3 py-2">Payments</th>
              <th className="px-3 py-2">Total</th><th className="px-3 py-2">Outstanding</th>
            </tr></thead>
            <tbody>{report.data?.typed_rows.map((row, index) => (
              <tr className="border-t border-line" key={`${row.makerspace_id ?? scopeKey}-${row.currency}-${row.subject_type}-${row.status}-${index}`}>
                {scopeKey === "all" ? <td className="px-3 py-2 font-mono">{row.makerspace_id}</td> : null}
                <td className="px-3 py-2 uppercase">{row.currency}</td>
                <td className="px-3 py-2">{label(row.subject_type)}</td>
                <td className="px-3 py-2">{label(row.status)}</td>
                <td className="px-3 py-2 font-mono">{row.payment_count}</td>
                <td className="px-3 py-2 font-mono">{money(row.amount_total, row.currency)}</td>
                <td className="px-3 py-2 font-mono font-semibold">{money(row.outstanding_amount, row.currency)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </DataState>
    </Panel>
  );
}

function label(value: string) {
  return value.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}

function money(amount: string, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: currency.toUpperCase() }).format(Number(amount));
  } catch {
    return `${currency.toUpperCase()} ${amount}`;
  }
}
