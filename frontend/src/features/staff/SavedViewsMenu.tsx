import { useContext, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Field, Modal } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import type { Paginated } from "../../lib/usePaginatedQuery";
import type { ListState } from "../../lib/useUrlListState";
import { StaffListContext } from "./StaffListContext";

type SavedView = { id: number; owner_username: string; name: string; state: ListState; shared: boolean };

export function SavedViewsMenu({ makerspaceId, entity, state, onRestore }: {
  makerspaceId: number; entity: string; state: ListState; onRestore: (state: ListState) => void;
}) {
  const { ownerName, canShare } = useContext(StaffListContext);
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  const key = ["saved-views", ownerName, makerspaceId, entity];
  const base = `/admin/makerspaces/${makerspaceId}/saved-views`;
  const views = useQuery({ queryKey: [...key, page], queryFn: () => staffRequest<Paginated<SavedView>>(`${base}?entity=${entity}&page=${page}`) });
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const save = useMutation({
    mutationFn: () => staffRequest<SavedView>(base, { method: "POST", body: JSON.stringify({ entity, name: name.trim(), state: Object.fromEntries(Object.entries(state).filter(([key]) => key !== "makerspace")), shared }) }),
    onSuccess: () => { setOpen(false); setName(""); setShared(false); void refresh(); },
  });
  const change = useMutation({
    mutationFn: ({ id, publish }: { id: number; publish?: boolean }) => staffRequest(`${base}/${id}`, publish === undefined
      ? { method: "DELETE" } : { method: "PATCH", body: JSON.stringify({ shared: publish }) }),
    onSuccess: () => { setPage(1); void refresh(); },
  });
  return <div className="my-3 flex flex-wrap items-center gap-2">
    <label className="text-xs text-muted">Saved views <select aria-label="Saved views" className="desk-input" value="" onChange={(event) => {
      const view = views.data?.results?.find((row) => row.id === Number(event.target.value));
      if (view) onRestore(view.state);
    }}><option value="">Choose a view</option>{views.data?.results?.map((view) => <option key={view.id} value={view.id}>{view.name}{view.shared ? " (shared)" : ""}</option>)}</select></label>
    <button type="button" className="desk-button-ghost" onClick={() => setOpen(true)}>Save current view</button>
    {views.data?.previous ? <button className="desk-button-ghost" onClick={() => setPage((p) => p - 1)}>Previous views</button> : null}
    {views.data?.next ? <button className="desk-button-ghost" onClick={() => setPage((p) => p + 1)}>More views</button> : null}
    <details><summary className="cursor-pointer text-sm">Manage saved views</summary>{views.data?.results?.filter((view) => view.owner_username === ownerName).map((view) => <div key={view.id} className="flex gap-2 py-1"><span>{view.name}</span>{canShare ? <button className="desk-button-ghost" disabled={change.isPending} onClick={() => change.mutate({ id: view.id, publish: !view.shared })}>{view.shared ? "Make private" : "Share to makerspace"}</button> : null}<button className="desk-button-ghost" disabled={change.isPending} onClick={() => change.mutate({ id: view.id })}>Delete {view.name}</button></div>)}</details>
    {views.error || change.error ? <p role="alert" className="text-sm text-danger">{(views.error ?? change.error)?.message}</p> : null}
    {open ? <Modal title="Save current view" open onClose={() => { setOpen(false); save.reset(); }}>
      <form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
        <Field label="View name"><input className="desk-input" maxLength={80} required value={name} onChange={(event) => setName(event.target.value)} /></Field>
        {canShare ? <label><input type="checkbox" checked={shared} onChange={(event) => setShared(event.target.checked)} /> Share to this makerspace</label> : null}
        {save.error ? <p role="alert" className="text-danger">{save.error.message}</p> : null}
        <button className="desk-button-primary" disabled={save.isPending || !name.trim()}>Save view</button>
      </form>
    </Modal> : null}
  </div>;
}
