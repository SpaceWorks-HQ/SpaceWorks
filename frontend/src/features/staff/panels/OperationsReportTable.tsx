import { formatReportCell, reportHeaders, reportRows, type ReportCell, type ReportRows } from "./OperationsReportState";

export function PerMakerspaceTables({ data, nameOf, emptyLabel = "No records." }: {
  data?: ReportRows; nameOf: (id: number) => string; emptyLabel?: string;
}) {
  if (!data?.rows?.length) return <p className="text-sm text-muted">{emptyLabel}</p>;
  const [header, ...body] = data.rows;
  const idx = header.findIndex((cell) => cell === "makerspace_id" || cell === "makerspace");
  if (idx === -1 || !body.length) return <ReportTable data={data} />;
  const groups = new Map<string, ReportCell[][]>();
  for (const row of body) {
    const key = String(row[idx]);
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  const subHeader = header.filter((_, index) => index !== idx);
  return (
    <div className="space-y-4">
      {[...groups].map(([key, rows]) => (
        <div key={key}><h4 className="eyebrow mb-1">{nameOf(Number(key))}</h4><ReportTable data={{ rows: [subHeader, ...rows.map((row) => row.filter((_, index) => index !== idx))] }} /></div>
      ))}
    </div>
  );
}

export function ReportTable({ data }: { data?: ReportRows }) {
  const headers = reportHeaders(data);
  const rows = reportRows(data);
  if (!headers.length || !rows.length) return <p className="text-sm text-muted">No records.</p>;
  return (
    <div className="mt-4 max-h-80 overflow-x-auto overflow-y-auto rounded-md border border-line">
      <table className="w-full divide-y divide-line text-left text-sm">
        <thead className="eyebrow sticky top-0 bg-surface"><tr>{headers.map((header) => <th scope="col" key={header} className="whitespace-nowrap px-3 py-2">{header.replace(/_/g, " ")}</th>)}</tr></thead>
        <tbody className="divide-y divide-line bg-bg text-ink">{rows.map((row, rowIndex) => <tr key={rowIndex}>{headers.map((header, cellIndex) => <td key={`${header}-${cellIndex}`} className="whitespace-nowrap px-3 py-2 font-mono text-sm">{formatReportCell(row[cellIndex])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
