import { dayStart } from "./calendarDates";

export type CalendarEntry = { id: string; startsAt: string; endsAt: string; label: string; href?: string };

/** A semantic table, not an interactive ARIA grid: each event link is a normal
 * keyboard target. Intervals appear on every local day they overlap.
 */
export function MonthCalendar({ month, entries, label, timeZone = "UTC" }: { month: string; entries: CalendarEntry[]; label: string; timeZone?: string }) {
  const [year, number] = month.split("-").map(Number);
  const start = new Date(Date.UTC(year, number - 1, 1));
  const days = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const offset = (start.getUTCDay() + 6) % 7;
  const cells = Array.from({ length: Math.ceil((offset + days) / 7) * 7 }, (_, index) => index - offset + 1);
  const weekday = new Intl.DateTimeFormat(undefined, { weekday: "short", timeZone: "UTC" });
  return <div className="mb-5 overflow-x-auto rounded-xl border border-line bg-panel">
    <table className="w-full min-w-[640px] table-fixed text-sm">
      <caption className="p-3 text-left font-semibold">{label} · {start.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" })} ({timeZone})</caption>
      <thead><tr>{Array.from({ length: 7 }, (_, index) => <th scope="col" className="border border-line p-2" key={index}>{weekday.format(new Date(Date.UTC(2026, 0, 5 + index)))}</th>)}</tr></thead>
      <tbody>{Array.from({ length: cells.length / 7 }, (_, row) => <tr key={row}>{cells.slice(row * 7, row * 7 + 7).map((day, index) => {
        if (day < 1 || day > days) return <td key={index} className="border border-line bg-surface" />;
        const date = dayStart(year, number, day, timeZone);
        const next = dayStart(year, number, day + 1, timeZone);
        const items = entries.filter((entry) => new Date(entry.startsAt) < next && new Date(entry.endsAt) > date);
        return <td className="h-24 border border-line p-2 align-top" key={index}>
          <span aria-label={date.toLocaleDateString(undefined, { dateStyle: "full", timeZone })} className="font-mono text-muted">{day}</span>
          <ul className="mt-1 space-y-1">{items.map((entry) => <li className="break-words" key={entry.id}>
            {entry.href ? <a href={entry.href} className="inline-flex min-h-11 items-center text-secondary-ink underline focus-visible:outline-2 focus-visible:outline-focus">{entry.label}</a> : <span>{entry.label}</span>}
          </li>)}</ul>
        </td>;
      })}</tr>)}</tbody>
    </table>
  </div>;
}
