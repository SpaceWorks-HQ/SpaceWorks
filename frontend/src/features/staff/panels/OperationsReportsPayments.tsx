import { BarChart, DataState } from "./OperationsReportsParts";
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

export function OperationsReportsPayments({ analyticsBase, scopeKey, startDate, endDate, enabled, makerspaceName }: {
  analyticsBase: string; scopeKey: number | "all"; startDate: string; endDate: string;
  enabled: boolean; makerspaceName: (id: number) => string;
}) {
  const query = new URLSearchParams();
  if (startDate) query.set("start", startDate);
  if (endDate) query.set("end", endDate);
  const report = useStaffGet<PaymentReport>(
    ["operations-report", "payment-reconciliation", scopeKey, startDate, endDate],
    `${analyticsBase}/payment-reconciliation?${query.toString()}`,
    enabled,
  );
  const rows = report.data?.typed_rows ?? [];

  return (
    <Panel title="Payment reconciliation">
      <p className="mb-3 text-xs text-muted">Private totals are grouped by makerspace, currency, subject, and status. Pending payments remain visible across date ranges.</p>
      <DataState loading={report.isLoading} error={report.error} empty={!rows.length}>
        {scopeKey === "all" ? (
          <div className="space-y-5">
            {paymentGroups(rows).map(([makerspaceId, group]) => (
              <section key={makerspaceId} className="rounded-md border border-line p-4">
                <h3 className="eyebrow">{makerspaceName(makerspaceId)}</h3>
                <PaymentChart rows={group} />
                <PaymentTable rows={group} />
              </section>
            ))}
          </div>
        ) : <><PaymentChart rows={rows} /><PaymentTable rows={rows} /></>}
      </DataState>
    </Panel>
  );
}

function PaymentChart({ rows }: { rows: PaymentReportRow[] }) {
  return <div className="mt-3 space-y-4">{currencyGroups(rows).map(([currency, group]) => (
    <section key={currency} className="rounded-md border border-line p-3">
      <h4 className="eyebrow">{currency.toUpperCase()}</h4>
      <div className="mt-2 grid gap-4 lg:grid-cols-2">
        <BarChart rows={group.map((row) => ({ label: label(row.status), value: row.payment_count }))} valueLabel="payments" />
        <BarChart rows={group.map((row) => ({ label: label(row.status), value: Number(row.amount_total) }))} valueLabel={`${currency.toUpperCase()} total`} />
      </div>
    </section>
  ))}</div>;
}

function PaymentTable({ rows }: { rows: PaymentReportRow[] }) {
  return (
    <div className="mt-4 overflow-x-auto rounded-md border border-line">
      <table className="w-full text-left text-sm">
        <thead className="eyebrow bg-surface"><tr>
          <th scope="col" className="px-3 py-2">Currency</th><th scope="col" className="px-3 py-2">Subject</th>
          <th scope="col" className="px-3 py-2">Status</th><th scope="col" className="px-3 py-2">Payments</th>
          <th scope="col" className="px-3 py-2">Total</th><th scope="col" className="px-3 py-2">Outstanding</th>
        </tr></thead>
        <tbody>{rows.map((row, index) => (
          <tr className="border-t border-line" key={`${row.currency}-${row.subject_type}-${row.status}-${index}`}>
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
  );
}

function paymentGroups(rows: PaymentReportRow[]) {
  const groups = new Map<number, PaymentReportRow[]>();
  for (const row of rows) {
    if (row.makerspace_id === undefined) continue;
    groups.set(row.makerspace_id, [...(groups.get(row.makerspace_id) ?? []), row]);
  }
  return [...groups];
}

function currencyGroups(rows: PaymentReportRow[]) {
  const groups = new Map<string, PaymentReportRow[]>();
  for (const row of rows) groups.set(row.currency, [...(groups.get(row.currency) ?? []), row]);
  return [...groups];
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
