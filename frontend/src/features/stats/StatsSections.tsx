import type {
  PublicStatsCurrentLoan,
  PublicStatsHardware,
  PublicStatsPrinting,
} from "./api";
import {
  BarChart,
  CompactList,
  Section,
  StatTile,
  formatDate,
  formatNumber,
} from "./StatsParts";
import { ImageThumbnail } from "../../components/ui/ImageThumbnail";

export function PrintingSection({ printing }: { printing: PublicStatsPrinting }) {
  const queueTotal =
    printing.jobs.queue.pending +
    printing.jobs.queue.accepted +
    printing.jobs.queue.printing;

  return (
    <Section title="Printing">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Print hours all time"
          value={formatNumber(printing.hours_all_time)}
          tone="blue"
        />
        <StatTile
          label="Print hours this month"
          value={formatNumber(printing.hours_this_month)}
          tone="yellow"
        />
        <StatTile
          label="Filament used"
          value={`${formatNumber(printing.grams_all_time)} g`}
          tone="mint"
        />
        <StatTile label="Completed jobs" value={printing.jobs.completed} tone="pink" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">Busiest printer</h3>
          {printing.busiest_printer ? (
            <div className="mt-3 flex items-center gap-3 text-sm">
              <ImageThumbnail
                src={printing.busiest_printer.image_url}
                alt={printing.busiest_printer.name}
                className="h-16 w-16"
              />
              <div className="min-w-0">
                <p className="break-words text-xl font-bold text-ink">
                  {printing.busiest_printer.name}
                </p>
                {printing.busiest_printer.model ? (
                  <p className="eyebrow break-words">
                    {printing.busiest_printer.model}
                  </p>
                ) : null}
                <p className="font-mono text-muted">
                  {formatNumber(printing.busiest_printer.hours)} hours /{" "}
                  {printing.busiest_printer.completed} completed
                </p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">No printer activity yet.</p>
          )}
        </div>

        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">Queue</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="status-box status-box-active">
              {printing.jobs.queue.pending} pending
            </span>
            <span className="status-box">
              {printing.jobs.queue.accepted} accepted
            </span>
            <span className="status-box">
              {printing.jobs.queue.printing} printing
            </span>
            <span className="status-box">{queueTotal} active</span>
          </div>
        </div>

        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">By brand</h3>
          <CompactList
            empty="No filament records."
            rows={printing.by_brand.map((row) => ({
              label: row.brand,
              value: `${formatNumber(row.grams)} g`,
            }))}
          />
        </div>
      </div>

      <div className="rounded-md border border-line bg-panel p-3">
        <h3 className="title-section mb-3">Filament trend</h3>
        <BarChart
          rows={printing.filament_trend.map((row) => ({
            label: row.period,
            value: row.grams,
          }))}
          valueLabel="g"
        />
      </div>

      <div className="rounded-md border border-line bg-panel p-3">
        <h3 className="title-section">Per printer</h3>
        {printing.per_printer.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="eyebrow py-2 pr-3">Printer</th>
                  <th className="eyebrow px-3 py-2 text-right">
                    Completed jobs
                  </th>
                  <th className="eyebrow px-3 py-2 text-right">Hours</th>
                  <th className="eyebrow py-2 pl-3 text-right">
                    Filament (g)
                  </th>
                </tr>
              </thead>
              <tbody>
                {printing.per_printer.map((row, index) => (
                  <tr
                    className="border-b border-line last:border-b-0"
                    key={`${row.name}-${index}`}
                  >
                    <td className="py-2 pr-3 text-ink">
                      <div className="flex items-center gap-3">
                        <ImageThumbnail src={row.image_url} alt={row.name} />
                        <span className="min-w-0 break-words">
                          {row.name}
                          {row.model ? (
                            <span className="eyebrow block">{row.model}</span>
                          ) : null}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-ink">{row.jobs}</td>
                    <td className="px-3 py-2 text-right font-mono text-ink">
                      {formatNumber(row.hours)}
                    </td>
                    <td className="py-2 pl-3 text-right font-mono text-ink">
                      {formatNumber(row.grams)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-muted">No printer activity yet.</p>
        )}
      </div>
    </Section>
  );
}

export function HardwareSection({ hardware }: { hardware: PublicStatsHardware }) {
  return (
    <Section title="Hardware">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Public library" value={hardware.library.library_size} tone="blue" />
        <StatTile
          label="Available now"
          value={hardware.library.available_count}
          tone="mint"
        />
        <StatTile
          label="Currently out"
          value={hardware.library.currently_out_count}
          tone="yellow"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">Most popular</h3>
          <CompactList
            empty="No lending history yet."
            rows={hardware.most_popular.map((row) => ({
              label: row.name,
              value: `${row.times_lent} loans / ${row.total_quantity_lent} total`,
            }))}
          />
        </div>
        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">Tools out</h3>
          <CompactList
            empty="No tools are out."
            rows={hardware.tools_out.map((row) => ({
              label: row.name,
              value: `${row.quantity_out} out`,
            }))}
          />
        </div>
        <div className="rounded-md border border-line bg-panel p-3">
          <h3 className="title-section">Recently added</h3>
          <CompactList
            empty="No new public gear this month."
            rows={hardware.recently_added.map((row) => ({
              label: row.name,
              value: formatDate(row.created_at),
            }))}
          />
        </div>
      </div>
    </Section>
  );
}

export function CurrentLoansSection({
  loans,
}: {
  loans: PublicStatsCurrentLoan[];
}) {
  return (
    <Section title="Currently out">
      {loans.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {loans.map((loan, index) => (
            <article
              className="rounded-md border border-line bg-panel p-3"
              key={`${loan.item_name}-${loan.holder_name}-${index}`}
            >
              <h3 className="title-section truncate">
                {loan.item_name}
              </h3>
              <p className="mt-2 text-sm text-muted">
                With <span className="font-semibold text-ink">{loan.holder_name}</span>
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <span className="status-box">
                  Due {loan.due ? formatDate(loan.due) : "not set"}
                </span>
                {loan.since ? (
                  <span className="status-box">Since {formatDate(loan.since)}</span>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted">No public tools are currently out.</p>
      )}
    </Section>
  );
}
