import type { ReactNode } from "react";

export type ListPresentation = { columns: string; density: string };
export function ListColumns({ columns, value, onChange }: {
  columns: { key: string; header: ReactNode }[]; value: ListPresentation;
  onChange: (value: ListPresentation) => void;
}) {
  const requested = value.columns.split(",");
  const existing = columns.filter(column => requested.includes(column.key)).map(column => column.key);
  const selected = existing.length ? existing : columns.map(column => column.key);
  return <div className="flex flex-wrap items-start gap-3 border-b border-line p-3">
    <details><summary className="desk-button-ghost cursor-pointer">Columns</summary>
      <fieldset className="grid gap-2 p-2"><legend className="sr-only">Visible columns</legend>
        {columns.map(column => <label key={column.key} className="flex min-h-11 items-center gap-2 text-sm">
          <input type="checkbox" checked={selected.includes(column.key)} disabled={selected.length === 1 && selected.includes(column.key)}
            onChange={event => onChange({ ...value, columns: columns.filter(item => item.key === column.key ? event.target.checked : selected.includes(item.key)).map(item => item.key).join(",") })} />{column.header}
        </label>)}
      </fieldset>
      <button className="desk-button-ghost" type="button" onClick={() => onChange({ ...value, columns: "" })}>Show all columns</button>
    </details>
    <label className="grid gap-1 text-xs text-muted">Density<select className="desk-input" value={value.density} onChange={event => onChange({ ...value, density: event.target.value })}>
      <option value="comfortable">Comfortable</option><option value="compact">Compact</option>
    </select></label>
  </div>;
}
