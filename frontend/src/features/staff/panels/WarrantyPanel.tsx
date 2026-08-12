import { Fragment, useState } from "react";

import { EmptyState, SkeletonRows } from "../../../components/ui";
import { WarrantyStatusBadge } from "../WarrantyStatusBadge";
import { WarrantySection } from "../WarrantySection";
import type { WarrantyReportRow, WarrantyStatus } from "../warrantyApi";
import { Panel, type Makerspace, useStaffGet } from "./shared";

type WarrantyResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: WarrantyReportRow[];
};

type StatusFilter = "all" | WarrantyStatus;

const PAGE_SIZE = 50;

export function WarrantyPanel({
  makerspace,
  canEditInventory,
}: {
  makerspace: Makerspace;
  canEditInventory: boolean;
}) {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [missingDocs, setMissingDocs] = useState(false);
  const [expiresBefore, setExpiresBefore] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const canManageRow = (row: WarrantyReportRow) => {
    if (row.host_kind === "asset") return canEditInventory;
    if (row.host_kind === "printer") return false;
    return true;
  };
  const queryParams = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (status !== "all") queryParams.set("status", status);
  if (missingDocs) queryParams.set("missing_docs", "true");
  if (expiresBefore) queryParams.set("expires_before", expiresBefore);
  const warranties = useStaffGet<WarrantyResponse>(
    ["warranties", makerspace.id, page, PAGE_SIZE, status, missingDocs, expiresBefore],
    `/admin/makerspace/${makerspace.id}/warranties?${queryParams.toString()}`,
  );

  const visibleRows = warranties.data?.results ?? [];
  const totalPages = Math.max(1, Math.ceil((warranties.data?.count ?? 0) / PAGE_SIZE));
  const scopeLabel = "equipment you can manage";
  const filtersActive = status !== "all" || missingDocs || Boolean(expiresBefore);

  function updateStatus(value: StatusFilter) {
    setStatus(value);
    setPage(1);
  }

  function updateMissingDocs(value: boolean) {
    setMissingDocs(value);
    setPage(1);
  }

  function updateExpiresBefore(value: string) {
    setExpiresBefore(value);
    setPage(1);
  }

  return (
    <Panel title="Warranties">
      <div className="mb-3 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm text-muted">Warranty coverage for {scopeLabel} in {makerspace.name}.</p>
          {warranties.data ? <p className="mt-1 font-mono text-xs text-muted">{warranties.data.count} hosts total</p> : null}
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="eyebrow grid gap-1 sm:w-48">
            Status
            <select className="desk-input" value={status} onChange={(event) => updateStatus(event.target.value as StatusFilter)}>
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="expiring_soon">Expiring soon</option>
              <option value="expired">Expired</option>
              <option value="unknown">Uncovered / no warranty</option>
            </select>
          </label>
          <label className="eyebrow grid gap-1 sm:w-44">
            Expires before
            <input className="desk-input" type="date" value={expiresBefore} onChange={(event) => updateExpiresBefore(event.target.value)} />
          </label>
          <label className="flex min-h-10 items-center gap-2 text-sm font-medium text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-line"
              checked={missingDocs}
              onChange={(event) => updateMissingDocs(event.target.checked)}
            />
            Missing docs
          </label>
        </div>
      </div>

      {warranties.isLoading ? <WarrantyTableSkeleton /> : null}
      {warranties.error instanceof Error ? <p className="mb-3 text-sm text-danger">{warranties.error.message}</p> : null}
      {!warranties.isLoading && !warranties.error && !visibleRows.length ? (
        <EmptyState title="No warranties" description={filtersActive ? "No hosts match these warranty filters." : "No warranty-covered hosts are in scope yet."} />
      ) : null}

      {visibleRows.length ? (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="min-w-[820px] divide-y divide-line text-left text-sm">
            <thead className="eyebrow bg-bg">
              <tr>
                <th className="px-3 py-2">Host</th>
                <th className="px-3 py-2">Vendor</th>
                <th className="px-3 py-2">Purchased</th>
                <th className="px-3 py-2">Expires</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Docs</th>
                <th className="px-3 py-2 text-right">Manage</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-surface">
              {visibleRows.map((row) => {
                const rowKey = `${row.host_kind}-${row.host_id}`;
                const isOpen = expanded === rowKey;
                const manageable = canManageRow(row);
                return (
                  <Fragment key={rowKey}>
                    <tr>
                      <td className="px-3 py-2 align-top">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded-md border border-line bg-bg px-2 py-0.5 text-xs font-medium text-muted">
                            {row.host_kind}
                          </span>
                          <span className="max-w-56 break-words font-medium text-ink">{row.host_label}</span>
                        </div>
                        {row.serial_number ? <p className="mt-1 text-xs text-muted">Serial: {row.serial_number}</p> : null}
                      </td>
                      <td className="px-3 py-2 align-top text-ink"><span className="block max-w-48 break-words">{row.vendor_name || "-"}</span></td>
                      <td className="whitespace-nowrap px-3 py-2 align-top text-muted">{formatDate(row.purchased_on)}</td>
                      <td className="whitespace-nowrap px-3 py-2 align-top text-muted">{formatDate(row.warranty_expires_on)}</td>
                      <td className="whitespace-nowrap px-3 py-2 align-top"><WarrantyStatusBadge status={row.status} /></td>
                      <td className="whitespace-nowrap px-3 py-2 text-right align-top text-muted">{row.document_count}</td>
                      <td className="whitespace-nowrap px-3 py-2 text-right align-top">
                        {manageable ? (
                          <button className="desk-button-ghost" type="button" onClick={() => setExpanded(isOpen ? null : rowKey)}>
                            {isOpen ? "Close" : "Manage"}
                          </button>
                        ) : <span className="text-xs text-muted">-</span>}
                      </td>
                    </tr>
                    {isOpen && manageable ? (
                      <tr key={`${rowKey}-edit`}>
                        <td colSpan={7} className="bg-bg px-3 py-3">
                          <WarrantySection hostKind={row.host_kind} hostId={row.host_id} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <button className="desk-button-ghost" type="button" disabled={!warranties.data?.previous} onClick={() => setPage((current) => Math.max(1, current - 1))}>
          Previous
        </button>
        <span className="font-mono text-muted">Page {page} of {totalPages}</span>
        <button className="desk-button-ghost" type="button" disabled={!warranties.data?.next} onClick={() => setPage((current) => current + 1)}>
          Next
        </button>
      </div>
    </Panel>
  );
}

function WarrantyTableSkeleton() {
  return (
    <div className="overflow-x-auto rounded-md border border-line" aria-hidden="true">
      <table className="min-w-[820px] divide-y divide-line text-left text-sm">
        <thead className="eyebrow bg-bg">
          <tr>
            {["Host", "Vendor", "Purchased", "Expires", "Status", "Docs", "Manage"].map((label) => (
              <th key={label} className="px-3 py-2">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line bg-surface">
          <SkeletonRows rows={4} cols={7} />
        </tbody>
      </table>
    </div>
  );
}

function formatDate(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}
