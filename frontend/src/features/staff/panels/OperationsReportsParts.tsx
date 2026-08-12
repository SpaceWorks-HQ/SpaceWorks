import type React from "react";

import { Skeleton, SkeletonRows } from "../../../components/ui";

export type ReportCell = string | number | boolean | null;
export type TypedReportRow = Record<string, ReportCell | undefined>;
export type ReportRows = { rows: ReportCell[][]; typed_rows?: TypedReportRow[] };

type ChartRow = { label: string; value: number };

export function reportRows(data?: ReportRows) {
  return data?.rows?.slice(1) ?? [];
}

function headers(data?: ReportRows) {
  return (data?.rows?.[0] ?? []).map(String);
}

function rowValue(row: ReportCell[], header: string[], key: string) {
  return row[header.indexOf(key)];
}

export function typedRows(data?: ReportRows) {
  return data?.typed_rows ?? [];
}

export function chartRows(data: ReportRows | undefined, labelKey: string, valueKey: string): ChartRow[] {
  const typed = typedRows(data);
  if (typed.length) {
    return typed
      .map((row) => ({
        label: String(row[labelKey] ?? "Unknown"),
        value: Number(row[valueKey] ?? 0),
      }))
      .filter((row) => row.value > 0);
  }

  const header = headers(data);
  return reportRows(data)
    .map((row) => ({
      label: String(rowValue(row, header, labelKey) ?? "Unknown"),
      value: Number(rowValue(row, header, valueKey) ?? 0),
    }))
    .filter((row) => row.value > 0);
}

export function DataState(props: { loading: boolean; error: unknown; empty: boolean; children: React.ReactNode }) {
  if (props.loading) return <ReportSkeleton />;
  if (props.error) return <p className="mt-3 text-sm text-danger">{props.error instanceof Error ? props.error.message : "Unable to load report."}</p>;
  if (props.empty) return <p className="mt-3 text-sm text-muted">No records.</p>;
  return <>{props.children}</>;
}

function ReportSkeleton() {
  return (
    <div className="mt-4 grid gap-3" aria-hidden="true">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="rounded-md border border-line bg-surface p-3">
            <Skeleton className="h-7 w-20" />
            <Skeleton className="mt-2 h-3 w-24" />
          </div>
        ))}
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full divide-y divide-line text-left text-sm">
          <tbody className="divide-y divide-line bg-bg">
            <SkeletonRows rows={4} cols={4} />
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Pastel fill + matching ink (with dark-mode deep-tint) so each report stat box
// carries a palette colour, cycled by position across the grid.
const STAT_TONE_CYCLE = [
  "border-accent bg-accent text-on-accent dark:bg-[#0b2a38] dark:text-[#7dd3fc]",
  "border-warn bg-warn text-on-warn dark:bg-[#332b00] dark:text-[#fcdf46]",
  "border-success bg-success text-on-success dark:bg-[#06281a] dark:text-[#74dd9c]",
  "border-secondary bg-secondary text-on-secondary dark:bg-[#3a1326] dark:text-[#f9a8d4]",
];

export function StatCards({ stats }: { stats: [string, number | undefined][] }) {
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {stats.map(([label, value], index) => (
        <div
          key={label}
          className={`rounded-md border p-3 ${STAT_TONE_CYCLE[index % STAT_TONE_CYCLE.length]}`}
        >
          <p className="text-2xl font-bold">{formatNumber(value ?? 0)}</p>
          <p className="text-xs opacity-70">{label}</p>
        </div>
      ))}
    </div>
  );
}

export function BarChart({ rows, valueLabel }: { rows: ChartRow[]; valueLabel?: string }) {
  const maxValue = Math.max(...rows.map((row) => row.value), 0);
  if (!rows.length || maxValue <= 0) return <p className="text-sm text-muted">No chart data.</p>;

  return (
    <div className="space-y-2" aria-label={`Bar chart of ${valueLabel ?? "values"}`} role="img">
      {rows.map((row, index) => {
        const width = `${Math.max((row.value / maxValue) * 100, 4)}%`;
        return (
          <div key={`${row.label}-${index}`} className="grid grid-cols-[minmax(0,1fr)_minmax(4rem,2fr)_auto] items-center gap-2 text-sm sm:grid-cols-[minmax(7rem,11rem)_1fr_auto]">
            <span className="truncate text-ink" title={row.label}>
              {row.label}
            </span>
            <div className="h-3 overflow-hidden rounded border border-line bg-bg">
              <div className="h-full rounded" style={{ width, backgroundColor: REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length] }} aria-hidden="true" />
            </div>
            <span className="min-w-14 text-right text-xs text-muted">
              {formatNumber(row.value)} {valueLabel ?? ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// Fixed categorical palette aligned to the pastel reskin. Kept dependency-free
// per repo convention - no chart library.
export const REPORT_CHART_COLORS = [
  "#0284c7",
  "#a16207",
  "#15803d",
  "#be185d",
  "#a4243b",
];

export function PieChart({ rows, valueLabel }: { rows: ChartRow[]; valueLabel?: string }) {
  const data = rows.filter((row) => row.value > 0);
  const total = data.reduce((sum, row) => sum + row.value, 0);
  if (!data.length || total <= 0) return <p className="text-sm text-muted">No chart data.</p>;

  const size = 160;
  const radius = 60;
  const strokeWidth = 26;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;

  let consumed = 0;
  const segments = data.map((row, index) => {
    const fraction = row.value / total;
    const dash = fraction * circumference;
    const segment = {
      color: REPORT_CHART_COLORS[index % REPORT_CHART_COLORS.length],
      dash,
      gap: circumference - dash,
      offset: -consumed,
      label: row.label,
      value: row.value,
      pct: fraction * 100,
    };
    consumed += dash;
    return segment;
  });

  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0" role="img" aria-label={`Pie chart of ${valueLabel ?? "values"}`}>
        <g transform={`rotate(-90 ${center} ${center})`} aria-hidden="true">
          <circle cx={center} cy={center} r={radius} fill="none" stroke="rgb(var(--color-line))" strokeWidth={strokeWidth} />
          {segments.map((segment, index) => (
            <circle
              key={`${segment.label}-${index}`}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={segment.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${segment.dash} ${segment.gap}`}
              strokeDashoffset={segment.offset}
            />
          ))}
        </g>
      </svg>
      <ul className="min-w-0 flex-1 space-y-1 text-sm">
        {segments.map((segment, index) => (
          <li key={`${segment.label}-legend-${index}`} className="flex items-center gap-2">
            <span className="h-3 w-3 shrink-0 rounded-full border border-line" style={{ backgroundColor: segment.color }} aria-hidden="true" />
            <span className="truncate text-ink" title={segment.label}>
              {segment.label}
            </span>
            <span className="ml-auto whitespace-nowrap text-xs text-muted">
              {formatNumber(segment.value)}
              {valueLabel ?? ""} - {segment.pct.toFixed(0)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Aggregate ("All makerspaces") leaderboards must read PER MAKERSPACE, not as one
// blended cross-Space Works ranking. Given rows whose first/identified column is the
// makerspace, this groups them and renders a separate ranked table per makerspace
// (heading = makerspace name), dropping the now-redundant makerspace column.
export function PerMakerspaceTables({
  data,
  nameOf,
  emptyLabel = "No records.",
}: {
  data?: ReportRows;
  nameOf: (id: number) => string;
  emptyLabel?: string;
}) {
  if (!data?.rows?.length) return <p className="text-sm text-muted">{emptyLabel}</p>;
  const [header, ...body] = data.rows;
  const idx = header.findIndex((cell) => cell === "makerspace_id" || cell === "makerspace");
  if (idx === -1 || !body.length) return <ReportTable data={data} />;

  const groups: { key: string; rows: ReportCell[][] }[] = [];
  const byKey = new Map<string, ReportCell[][]>();
  for (const row of body) {
    const key = String(row[idx]);
    let bucket = byKey.get(key);
    if (!bucket) {
      bucket = [];
      byKey.set(key, bucket);
      groups.push({ key, rows: bucket });
    }
    bucket.push(row);
  }
  const subHeader = header.filter((_, i) => i !== idx);

  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <div key={group.key}>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{nameOf(Number(group.key))}</h4>
          <ReportTable data={{ rows: [subHeader, ...group.rows.map((row) => row.filter((_, i) => i !== idx))] }} />
        </div>
      ))}
    </div>
  );
}

export function ReportTable({ data }: { data?: ReportRows }) {
  const tableHeaders = headers(data);
  const rows = reportRows(data);
  if (!tableHeaders.length || !rows.length) return <p className="text-sm text-muted">No records.</p>;

  return (
    <div className="mt-4 max-h-80 overflow-x-auto overflow-y-auto rounded-md border border-line">
      <table className="w-full divide-y divide-line text-left text-sm">
        <thead className="sticky top-0 bg-surface text-xs uppercase tracking-wide text-muted">
          <tr>
            {tableHeaders.map((header) => (
              <th key={header} className="whitespace-nowrap px-3 py-2 font-semibold">
                {header.replace(/_/g, " ")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-bg text-ink">
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {tableHeaders.map((header, cellIndex) => (
                <td key={`${header}-${cellIndex}`} className="whitespace-nowrap px-3 py-2 text-sm">
                  {formatCell(row[cellIndex])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: ReportCell | undefined) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (/^\d{4}-\d{2}-\d{2}T/.test(value)) return new Date(value).toLocaleString();
  return value;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}
