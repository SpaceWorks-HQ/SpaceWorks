import { currentMonth, useDiscoveryState } from "./useDiscoveryState";

export function DiscoveryControls({ state, searchLabel, filters }: {
  state: ReturnType<typeof useDiscoveryState>;
  searchLabel: string;
  filters: { value: string; label: string }[];
}) {
  return <div className="desk-panel mb-5 flex flex-wrap items-end gap-3 p-4">
    <label className="min-w-0 flex-1 text-sm font-semibold">{searchLabel}
      <input type="search" className="desk-input mt-1 w-full" value={state.query} onChange={(event) => state.update({ q: event.target.value })} />
    </label>
    <label className="text-sm font-semibold">Filter
      <select className="desk-input mt-1" value={state.facet} onChange={(event) => state.update({ filter: event.target.value })}>
        <option value="">All</option>{filters.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
      </select>
    </label>
    <label className="text-sm font-semibold">Month
      <input type="month" min="1900-01" max="9998-12" className="desk-input mt-1" value={state.month} onChange={(event) => state.update({ month: event.target.value })} />
    </label>
    <div className="flex flex-wrap gap-2" role="group" aria-label="Discovery view">
      <button type="button" className="desk-button" aria-pressed={state.view === "agenda"} onClick={() => state.update({ view: "" })}>List</button>
      <button type="button" className="desk-button" aria-pressed={state.view === "calendar"} onClick={() => state.update({ view: "calendar", month: state.month || currentMonth(state.timeZone) })}>Month calendar</button>
      <button type="button" className="desk-button-ghost" onClick={() => state.update({ q: "", filter: "", month: "", view: "" })}>Clear filters</button>
    </div>
  </div>;
}
