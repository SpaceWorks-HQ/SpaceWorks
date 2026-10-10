import type { UrlListState } from "../../lib/useUrlListState";
import { SavedViewsMenu } from "./SavedViewsMenu";

export function ListViewControls({ state, makerspaceId, entity, sorts, search = true }: {
  state: UrlListState; makerspaceId: number; entity: string; sorts: readonly (readonly [string, string])[]; search?: boolean;
}) {
  return <div className="mb-3">
    <div className="flex flex-wrap gap-3">
      {state.values.id ? <button className="desk-button-ghost" type="button" onClick={() => state.setFilter("id", "")}>Clear selected result</button> : null}
      {search ? <label className="grid gap-1 text-xs text-muted">Search<input className="desk-input" value={state.values.q ?? ""} onChange={(event) => state.setFilter("q", event.target.value)} /></label> : null}
      <label className="grid gap-1 text-xs text-muted">Sort<select className="desk-input" value={state.values.ordering} onChange={(event) => state.setFilter("ordering", event.target.value)}>{sorts.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </div>
    <SavedViewsMenu makerspaceId={makerspaceId} entity={entity} state={state.values} onRestore={state.restore} />
  </div>;
}
