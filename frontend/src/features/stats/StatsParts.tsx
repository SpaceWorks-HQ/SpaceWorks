import type React from "react";

type ChartRow = { label: string; value: number };

export type StatTone = "blue" | "yellow" | "mint" | "pink";

// Pastel fill + matching ink, with the dark-mode deep-tint companion used
// across the reskin. Each stat box picks one so the grid reads as a colourful
// palette rather than a wall of identical surface tiles.
export const STAT_TONE_CLASS: Record<StatTone, string> = {
  blue:
    "border-accent bg-accent text-on-accent dark:bg-accent/15 dark:text-accent-ink",
  yellow:
    "border-warn bg-warn text-on-warn dark:bg-warn/15 dark:text-warn-ink",
  mint:
    "border-success bg-success text-on-success dark:bg-success/15 dark:text-success-ink",
  pink:
    "border-secondary bg-secondary text-on-secondary dark:bg-secondary/15 dark:text-secondary-ink",
};

export function StatTile({
  label,
  value,
  tone = "blue",
}: {
  label: string;
  value: number | string;
  tone?: StatTone;
}) {
  return (
    <div className={`rounded-md border p-3 ${STAT_TONE_CLASS[tone]}`}>
      <p className="font-mono text-2xl font-bold">{value}</p>
      <p className="eyebrow mt-1 text-current opacity-70">{label}</p>
    </div>
  );
}

export function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="desk-panel overflow-hidden">
      <div className="border-b border-line bg-surface px-4 py-3">
        <h2 className="title-panel">{title}</h2>
      </div>
      <div className="space-y-4 p-4">{children}</div>
    </section>
  );
}

export function CompactList({
  rows,
  empty,
}: {
  rows: { label: string; value: string }[];
  empty: string;
}) {
  if (!rows.length) {
    return <p className="mt-3 text-sm text-muted">{empty}</p>;
  }

  return (
    <ul className="mt-3 space-y-2 text-sm">
      {rows.map((row) => (
        <li className="flex min-w-0 items-start gap-3" key={`${row.label}-${row.value}`}>
          <span className="min-w-0 flex-1 truncate text-ink" title={row.label}>
            {row.label}
          </span>
          <span className="eyebrow shrink-0 text-right">{row.value}</span>
        </li>
      ))}
    </ul>
  );
}

export function BarChart({
  rows,
  valueLabel,
}: {
  rows: ChartRow[];
  valueLabel: string;
}) {
  const maxValue = Math.max(...rows.map((row) => row.value), 0);
  if (!rows.length || maxValue <= 0) {
    return <p className="text-sm text-muted">No chart data.</p>;
  }

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const width = `${Math.max((row.value / maxValue) * 100, 4)}%`;
        return (
          <div
            className="grid grid-cols-[minmax(0,1fr)_minmax(4rem,2fr)_auto] items-center gap-2 text-sm sm:grid-cols-[minmax(7rem,11rem)_1fr_auto]"
            key={row.label}
          >
            <span className="truncate text-ink" title={row.label}>
              {row.label}
            </span>
            <div className="h-3 overflow-hidden rounded bg-bg">
              <div className="h-full rounded bg-secondary" style={{ width }} />
            </div>
            <span className="eyebrow min-w-14 text-right">
              {formatNumber(row.value)} {valueLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
}

export function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
