import { useEffect, useMemo, useState } from "react";

import { downloadStaffFile } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import {
  formatDate,
  isOverdue,
  ledgerParams,
  LedgerSkeleton,
  SortableHeader,
  UnitLines,
  sourceLabels,
  type LedgerResponse,
  type LedgerSourceFilter,
  type SortKey,
  type SortDirection,
} from "./LedgerParts";
import { Panel, type Makerspace, useStaffGet } from "./shared";

const LEDGER_PAGE_SIZE = 50;

export function Ledger({ makerspace, isSuperadmin }: { makerspace: Makerspace; isSuperadmin: boolean }) {
  const [allMakerspaces, setAllMakerspaces] = useState(false);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState<LedgerSourceFilter>("");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [sort, setSort] = useState<{ key: SortKey; direction: SortDirection }>({
    key: "due",
    direction: "asc",
  });
  const debouncedFilter = useDebouncedValue(filter);
  const aggregate = isSuperadmin && allMakerspaces;
  const ledgerPath = aggregate ? "/admin/ledger" : `/admin/makerspace/${makerspace.id}/ledger`;
  const sortParam = `${sort.direction === "desc" ? "-" : ""}${sort.key}`;
  const ledgerQuery = useMemo(() => {
    const params = ledgerParams({
      page,
      pageSize: LEDGER_PAGE_SIZE,
      search: debouncedFilter,
      source: sourceFilter,
      overdueOnly,
      sort: sortParam,
    });
    return params.toString();
  }, [debouncedFilter, overdueOnly, page, sortParam, sourceFilter]);
  const exportQuery = useMemo(() => {
    const params = ledgerParams({
      search: debouncedFilter,
      source: sourceFilter,
      overdueOnly,
      sort: sortParam,
    });
    return params.toString();
  }, [debouncedFilter, overdueOnly, sortParam, sourceFilter]);
  const ledger = useStaffGet<LedgerResponse>(
    ["ledger", aggregate ? "all" : makerspace.id, ledgerQuery],
    `${ledgerPath}?${ledgerQuery}`,
  );

  useEffect(() => {
    setPage(1);
  }, [aggregate, debouncedFilter, makerspace.id, overdueOnly, sort.direction, sort.key, sourceFilter]);

  const rows = ledger.data?.results ?? [];
  const now = Date.now();
  const itemCount = rows.reduce((total, row) => total + row.quantity, 0);
  const totalRows = ledger.data?.count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalRows / LEDGER_PAGE_SIZE));

  const setSortKey = (key: SortKey) => {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "asc" ? "desc" : "asc",
    }));
  };

  const exportLedger = (format: "csv" | "xlsx") => {
    const params = new URLSearchParams(exportQuery);
    params.set("format", format);
    const filename = aggregate ? `ledger-all.${format}` : `ledger-${makerspace.slug}.${format}`;
    void downloadStaffFile(`${ledgerPath}/export?${params.toString()}`, filename);
  };

  return (
    <Panel title="Ledger">
      <div className="grid gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-lg font-semibold text-ink">{itemCount} items out</p>
            <p className="text-sm text-muted">
              {aggregate ? "Across all makerspaces" : makerspace.name}
              {ledger.data ? ` - ${ledger.data.count} records` : ""}
            </p>
          </div>
          {isSuperadmin ? (
            <label className="inline-flex items-center gap-2 text-sm font-medium text-ink">
              <input
                type="checkbox"
                checked={allMakerspaces}
                onChange={(event) => {
                  setAllMakerspaces(event.target.checked);
                  setPage(1);
                }}
              />
              All makerspaces
            </label>
          ) : null}
        </div>

        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_180px_140px_auto_auto] md:items-center">
          <input
            className="desk-input"
            placeholder="Search holder, email, item, or box"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          <select className="desk-input" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as LedgerSourceFilter)}>
            <option value="">All sources</option>
            <option value="reviewed">Reviewed</option>
            <option value="self_checkout">Self-checkout</option>
            <option value="direct">Direct</option>
          </select>
          <label className="inline-flex items-center gap-2 text-sm font-medium text-ink">
            <input type="checkbox" checked={overdueOnly} onChange={(event) => setOverdueOnly(event.target.checked)} />
            Overdue
          </label>
          <button className="desk-button-ghost" type="button" onClick={() => exportLedger("csv")}>Export CSV</button>
          <button className="desk-button-ghost" type="button" onClick={() => exportLedger("xlsx")}>Export XLSX</button>
        </div>

        {ledger.isLoading ? <LedgerSkeleton aggregate={aggregate} /> : null}
        {ledger.error ? <p className="text-sm text-danger">{ledger.error.message}</p> : null}
        {!ledger.isLoading && !ledger.error && !rows.length ? (
          <p className="rounded-md border border-line bg-surface p-3 text-sm text-muted">No items are currently out.</p>
        ) : null}

        {rows.length ? (
          <div className="overflow-x-auto rounded-md border border-line">
            <table className="min-w-[760px] divide-y divide-line text-left text-sm">
              <thead className="eyebrow bg-bg">
                <tr>
                  <SortableHeader label="Item" sortKey="item_name" sort={sort} onSort={setSortKey} />
                  <SortableHeader label="Holder" sortKey="holder" sort={sort} onSort={setSortKey} />
                  <SortableHeader label="Qty" sortKey="quantity" sort={sort} onSort={setSortKey} align="right" />
                  <SortableHeader label="Out since" sortKey="since" sort={sort} onSort={setSortKey} />
                  <SortableHeader label="Due" sortKey="due" sort={sort} onSort={setSortKey} />
                  <SortableHeader label="Source" sortKey="source" sort={sort} onSort={setSortKey} />
                  {aggregate ? <SortableHeader label="Makerspace" sortKey="makerspace_id" sort={sort} onSort={setSortKey} /> : null}
                </tr>
              </thead>
              <tbody className="divide-y divide-line bg-surface">
                {rows.map((row) => {
                  const overdue = isOverdue(row.due, now);
                  return (
                    <tr key={`${row.source}-${row.reference_id}-${row.makerspace_id}-${row.item_name}`} className={overdue ? "bg-danger/10" : ""}>
                      <td className="px-3 py-2 align-top">
                        <div className="max-w-56 break-words font-medium text-ink">{row.item_name}</div>
                        {row.container ? <div className="mt-0.5 break-words text-xs text-muted">Box: {row.container}</div> : null}
                        <UnitLines row={row} />
                      </td>
                      <td className="px-3 py-2 align-top text-ink"><span className="block max-w-48 break-words">{row.holder}</span></td>
                      <td className="whitespace-nowrap px-3 py-2 text-right font-mono font-semibold text-ink">{row.quantity}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted">{formatDate(row.since)}</td>
                      <td className={`whitespace-nowrap px-3 py-2 ${overdue ? "font-semibold text-danger" : "text-muted"}`}>
                        <span className="inline-flex items-center gap-2">
                          {formatDate(row.due)}
                          {overdue ? <span className="status-box status-box-danger">Overdue</span> : null}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span className="rounded-md border border-line bg-bg px-2 py-0.5 text-xs font-medium text-muted">
                          {sourceLabels[row.source]}
                        </span>
                      </td>
                      {aggregate ? <td className="whitespace-nowrap px-3 py-2 text-muted">#{row.makerspace_id}</td> : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        {ledger.data && totalRows > LEDGER_PAGE_SIZE ? (
          <div className="flex flex-wrap items-center justify-end gap-2 text-sm text-muted">
            <button className="desk-button-ghost" type="button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
              Previous
            </button>
            <span className="font-mono">Page {page} of {totalPages}</span>
            <button className="desk-button-ghost" type="button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
              Next
            </button>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
