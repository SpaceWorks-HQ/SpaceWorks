import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";
import { StocktakeDiscipline } from "./StocktakeDiscipline";
import { CountSection } from "./StocktakeCountSection";
import { useUrlListState } from "../../../lib/useUrlListState";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { Panel, type Makerspace, useStaffGet } from "./shared";
import { invalidateInventoryViews } from "../queryInvalidation";

type ContainerOption = { id: number; label: string; location?: string };
type StocktakeRow = { variance_threshold?: number | null; approval_required?: boolean; id: number; status: string; notes: string; container: number | null };
export function StocktakePanel({ makerspace, isSuperadmin = false, canConfigure = false }: { makerspace: Makerspace; isSuperadmin?: boolean; canConfigure?: boolean }) {
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<number | null>(null);
  const [blind, setBlind] = useState("");
  const discipline = makerspace.enabled_features?.includes("stocktake.discipline");
  const [createNotes, setCreateNotes] = useState("Cycle count");
  const [createContainerId, setCreateContainerId] = useState("");
  const list = useUrlListState({ status: "", page: "1" });
  const stocktakes = usePaginatedQuery<StocktakeRow>({
    key: ["stocktakes", makerspace.id, list.values.status],
    page: list.page, onPageChange: list.setPage,
    path: `/admin/makerspace/${makerspace.id}/stocktakes?status=${encodeURIComponent(list.values.status)}`,
    resetKey: String(makerspace.id),
  });
  const containers = useStaffGet<{ results: ContainerOption[] }>(["stocktake-containers", makerspace.id], `/admin/makerspace/${makerspace.id}/containers?page_size=1000`);
  const create = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/makerspace/${makerspace.id}/stocktakes`, {
        method: "POST",
        body: JSON.stringify({
          notes: createNotes,
          ...(discipline && blind !== "" ? { blind: blind === "true" } : {}),
          container_id: createContainerId ? Number(createContainerId) : null,
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] }),
  });
  const action = useMutation({
    mutationFn: (path: string) => staffRequest(path, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (_data, path) => {
      queryClient.invalidateQueries({ queryKey: ["stocktakes", makerspace.id] });
      if (path.endsWith("/apply-adjustments")) {
        invalidateInventoryViews(queryClient, makerspace.id);
        queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      }
    },
  });
  const createError = create.error instanceof Error ? create.error.message : undefined;
  const actionError = action.error instanceof Error ? action.error.message : undefined;

  return (
    <Panel title="Stocktake">
      {discipline && canConfigure ? <StocktakeDiscipline makerspaceId={makerspace.id} /> : null}
      {discipline ? <label className="my-2 grid gap-1 text-sm">Count visibility<select className="desk-input" value={blind} onChange={event => setBlind(event.target.value)}><option value="">Use makerspace policy</option><option value="true">Blind (hide expected quantities)</option><option value="false">Show expected quantities</option></select></label> : null}
      <label className="eyebrow mb-3 grid gap-1">Status<select className="desk-input" value={list.values.status} onChange={event => list.setFilter("status", event.target.value)}><option value="">All</option>{["draft", "counting", "completed", "approved", "applied", "cancelled"].map(status => <option key={status} value={status}>{status}</option>)}</select></label>
      <div className="grid gap-2 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="eyebrow grid gap-1">
          <span>Session notes</span>
          <input className="desk-input" value={createNotes} onChange={(event) => setCreateNotes(event.target.value)} />
        </label>
        <label className="eyebrow grid gap-1">
          <span>Container</span>
          <select className="desk-input" value={createContainerId} onChange={(event) => setCreateContainerId(event.target.value)}>
            <option value="">All containers</option>
            {containers.data?.results.map((container) => <option key={container.id} value={container.id}>{container.label}</option>)}
          </select>
        </label>
        <button className="desk-button-primary" disabled={create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Starting..." : "Start stocktake"}
        </button>
      </div>
      {createError ? <p className="mt-2 text-sm text-danger">{createError}</p> : null}
      {actionError ? <p className="mt-2 text-sm text-danger">{actionError}</p> : null}
      <div className="mt-3 grid gap-2">
        {stocktakes.results.map((row) => (
          <div key={row.id} className="rounded-md border border-line bg-surface p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong className="font-mono">#{row.id}</strong>
              <span className="rounded-md border border-line bg-bg px-2 py-0.5 text-xs text-muted">{row.status}</span>
              {canCount(row.status) ? (
                <button className="desk-button-ghost" type="button" onClick={() => setOpenId((id) => (id === row.id ? null : row.id))}>{openId === row.id ? "Hide counts" : "Count items"}</button>
              ) : null}
              {row.status === "counting" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/complete`)}>Complete</button>
              ) : null}
              {(isSuperadmin || (canConfigure && row.variance_threshold != null)) && row.status === "completed" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/approve`)}>Approve</button>
              ) : null}
              {(isSuperadmin || row.approval_required === false || (canConfigure && row.variance_threshold != null)) && row.status === "approved" ? (
                <button className="desk-button-success" type="button" disabled={action.isPending} onClick={() => action.mutate(`/admin/stocktakes/${row.id}/apply-adjustments`)}>Apply</button>
              ) : null}
            </div>
            <p className="mt-1 text-muted">{row.notes}{row.container ? ` ? Container #${row.container}` : ""}</p>
            {openId === row.id ? <CountSection makerspace={makerspace} stocktakeId={row.id} /> : null}
          </div>
        ))}
      </div>
      <Pagination page={stocktakes.page} totalPages={stocktakes.totalPages} onChange={stocktakes.setPage} count={stocktakes.count} pageSize={stocktakes.pageSize} />
    </Panel>
  );
}

function canCount(status: string) {
  return status === "draft" || status === "counting";
}
