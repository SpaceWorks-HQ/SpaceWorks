import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteReportView, getReportView, listReportViews, saveReportView, type ReportViewState } from "./reportViewsApi";

export function ServerReportViews({ makerspaceId, state, fields, onColumns, onApply }: {
  makerspaceId: number; state: ReportViewState; fields: string[];
  onColumns: (columns: string[]) => void; onApply: (state: ReportViewState) => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const [page, setPage] = useState(1);
  const key = ["saved-report-views", makerspaceId];
  const views = useQuery({ queryKey: [...key, page], queryFn: () => listReportViews(makerspaceId, page) });
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const save = useMutation({
    mutationFn: () => saveReportView(makerspaceId, name.trim(), state, shared),
    onSuccess: () => { setName(""); refresh(); },
  });
  // Fetch at open time: a cached shared view cannot bypass owner reauthorization.
  const open = useMutation({ mutationFn: (pk: number) => getReportView(makerspaceId, pk), onSuccess: (view) => onApply(view.state) });
  const remove = useMutation({ mutationFn: (pk: number) => deleteReportView(makerspaceId, pk), onSuccess: refresh });
  const error = save.error ?? open.error ?? remove.error ?? views.error;
  return <div className="mt-4 space-y-3 border-t border-line pt-3">
    <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
      <label className="eyebrow grid gap-1">View name<input className="desk-input" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} required /></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} />Share with makerspace (managers)</label>
      <button className="desk-button-primary" disabled={!name.trim() || save.isPending}>Save view</button>
    </form>
    <fieldset className="flex flex-wrap gap-2"><legend className="eyebrow">Visible columns (none selected shows all)</legend>
      {fields.map((field) => <label className="text-xs" key={field}><input type="checkbox" checked={state.columns.includes(field)} onChange={(event) => onColumns(event.target.checked ? [...state.columns, field] : state.columns.filter((value) => value !== field))} /> {field.replace(/_/g, " ")}</label>)}
    </fieldset>
    {views.isLoading ? <p className="text-sm text-muted">Loading saved views...</p> : null}
    <div className="flex flex-wrap gap-2">{views.data?.results?.map((view) => <div key={view.id} className="flex items-center gap-2 rounded border border-line p-2">
      <button className="desk-button-ghost" disabled={open.isPending} onClick={() => open.mutate(view.id)}>{view.name}{view.shared ? " (shared)" : ""}</button>
      <button className="desk-button-ghost" disabled={remove.isPending} aria-label={`Delete ${view.name}`} onClick={() => remove.mutate(view.id)}>Delete</button>
    </div>)}</div>
    {(views.data?.previous || views.data?.next) ? <div className="flex gap-2">
      <button className="desk-button" disabled={!views.data.previous} onClick={() => setPage((value) => value - 1)}>Previous views</button>
      <button className="desk-button" disabled={!views.data.next} onClick={() => setPage((value) => value + 1)}>Next views</button>
    </div> : null}
    {error ? <p role="alert" className="text-sm text-danger">{error instanceof Error ? error.message : "Could not update saved views."}</p> : null}
  </div>;
}
