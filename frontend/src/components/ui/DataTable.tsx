import type { Key, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "./EmptyState";
import { SkeletonRows } from "./Skeleton";
import { Spinner } from "./Spinner";

export type DataTableColumn<T> = {
  key: Extract<keyof T, string> | string; header: ReactNode; render?: (row: T) => ReactNode; sortable?: boolean; className?: string;
};

type SortState = { key: string; direction: "asc" | "desc" };

type DataTableProps<T> = {
  columns: DataTableColumn<T>[]; data: T[]; getRowId?: (row: T) => Key; selectedIds?: Key[];
  onSelectionChange?: (ids: Key[]) => void; loading?: boolean; emptyTitle?: string; emptyDescription?: string; emptyAction?: ReactNode;
  skeletonCols?: number;
};

export function DataTable<T>({
  columns,
  data,
  getRowId = defaultGetRowId,
  selectedIds,
  onSelectionChange,
  loading = false,
  emptyTitle = "No records",
  emptyDescription,
  emptyAction,
  skeletonCols,
}: DataTableProps<T>) {
  const [sort, setSort] = useState<SortState | null>(null);
  const selectedSet = useMemo(() => new Set(selectedIds ?? []), [selectedIds]);
  const visibleIds = useMemo(() => data.map(getRowId), [data, getRowId]);
  const selectionEnabled = Boolean(selectedIds && onSelectionChange);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedSet.has(id));
  const someSelected = visibleIds.some((id) => selectedSet.has(id));
  const selectAllRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected && !allSelected;
  }, [allSelected, someSelected]);

  const sortedData = useMemo(() => {
    if (!sort) return data;
    return [...data].sort((a, b) => compareValues(getCellValue(a, sort.key), getCellValue(b, sort.key), sort.direction));
  }, [data, sort]);

  const toggleSort = (column: DataTableColumn<T>) => {
    if (!column.sortable) return;
    setSort((current) => ({
      key: column.key,
      direction: current?.key === column.key && current.direction === "asc" ? "desc" : "asc",
    }));
  };
  const changeRow = (id: Key, checked: boolean) => {
    const next = new Set(selectedSet);
    checked ? next.add(id) : next.delete(id);
    onSelectionChange?.([...next]);
  };
  const changeAll = (checked: boolean) => {
    const next = new Set(selectedSet);
    visibleIds.forEach((id) => (checked ? next.add(id) : next.delete(id)));
    onSelectionChange?.([...next]);
  };

  if (!loading && !data.length) return <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />;

  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-panel">
      <table className="w-full min-w-[640px] text-left text-sm" aria-busy={loading}>
        <thead className="bg-surface text-xs text-muted">
          <tr className="border-b border-line">
            {selectionEnabled ? (
              <th className="w-10 px-3 py-2" scope="col">
                <input ref={selectAllRef} type="checkbox" aria-label="Select all rows" checked={allSelected} onChange={(event) => changeAll(event.target.checked)} />
              </th>
            ) : null}
            {columns.map((column) => (
              <th
                key={column.key}
                className={`px-3 py-2 font-semibold ${column.className ?? ""}`}
                aria-sort={sort?.key === column.key ? ariaSort(sort.direction) : undefined}
                scope="col"
              >
                {column.sortable ? (
                  <button type="button" className="inline-flex items-center gap-1 font-semibold" onClick={() => toggleSort(column)}>
                    {column.header}
                    <span aria-hidden="true">{sort?.key === column.key ? sort.direction : "sort"}</span>
                  </button>
                ) : column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && skeletonCols ? (
            <SkeletonRows rows={6} cols={skeletonCols} />
          ) : loading ? (
            <tr>
              <td className="px-3 py-8 text-center" colSpan={columns.length + (selectionEnabled ? 1 : 0)}>
                <Spinner />
              </td>
            </tr>
          ) : (
            sortedData.map((row) => {
              const id = getRowId(row);
              return (
                <tr key={id} className="border-b border-line last:border-b-0">
                  {selectionEnabled ? (
                    <td className="px-3 py-2">
                      <input type="checkbox" aria-label={`Select row ${String(id)}`} checked={selectedSet.has(id)} onChange={(event) => changeRow(id, event.target.checked)} />
                    </td>
                  ) : null}
                  {columns.map((column) => (
                    <td key={column.key} className={`px-3 py-2 text-ink ${column.className ?? ""}`}>
                      {column.render ? column.render(row) : String(getCellValue(row, column.key) ?? "")}
                    </td>
                  ))}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function defaultGetRowId<T>(row: T): Key {
  return (row as { id: Key }).id;
}

function getCellValue<T>(row: T, key: string) {
  return (row as Record<string, unknown>)[key];
}

function ariaSort(direction: "asc" | "desc") {
  return direction === "asc" ? "ascending" : "descending";
}

function compareValues(left: unknown, right: unknown, direction: "asc" | "desc") {
  const order = direction === "asc" ? 1 : -1;
  if (left == null && right == null) return 0;
  if (left == null) return -1 * order;
  if (right == null) return 1 * order;
  if (typeof left === "number" && typeof right === "number") return (left - right) * order;
  return String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: "base" }) * order;
}
