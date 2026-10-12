import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../../lib/api";
import { Pagination } from "../../../components/ui/Pagination";

type Suggestion = { id: number; name: string; available_quantity: number; reorder_point: number; reorder_quantity: number; supplier: string; sku: string };

export function ReorderSuggestions({ makerspaceId, canProcure }: { makerspaceId: number; canProcure: boolean }) {
  const [page, setPage] = useState(1);
  const [message, setMessage] = useState("");
  const client = useQueryClient();
  const suggestions = useQuery({ queryKey: ["reorder-suggestions", makerspaceId, page],
    queryFn: () => staffRequest<{ count: number; results: Suggestion[] }>(`/admin/makerspace/${makerspaceId}/inventory/reorder-suggestions?page=${page}`) });
  const create = useMutation({ mutationFn: (productId: number) => staffRequest<{ id: number }>(
    `/admin/makerspace/${makerspaceId}/inventory/reorder-draft`, { method: "POST", body: JSON.stringify({ product_id: productId }) }),
    onSuccess: (result) => { setMessage(`Procurement draft #${result.id} is ready in To Buy.`);
      client.invalidateQueries({ queryKey: ["procurement", makerspaceId] }); },
  });
  return <div className="grid gap-2 rounded-md border border-line p-3">
    <h3 className="title-section">Reorder suggestions</h3>
    {suggestions.isLoading ? <p role="status" className="text-sm text-muted">Loading suggestions...</p> : null}
    {suggestions.error || create.error ? <p role="alert" className="text-sm text-danger">{(suggestions.error || create.error)?.message}</p> : null}
    {message ? <p role="status" className="text-sm text-muted">{message}</p> : null}
    {suggestions.data?.results.map((row) => <div key={row.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <p>{row.name}: {row.available_quantity} available, reorder at {row.reorder_point}{row.supplier ? ` · ${row.supplier}` : ""}</p>
      {canProcure ? <button className="desk-button-primary" type="button" disabled={create.isPending || row.reorder_quantity < 1}
        onClick={() => create.mutate(row.id)}>Draft order for {row.reorder_quantity}</button> : null}
    </div>)}
    {suggestions.isSuccess && !suggestions.data.results.length ? <p className="text-sm text-muted">No products are at their reorder points.</p> : null}
    <Pagination page={page} totalPages={Math.max(1, Math.ceil((suggestions.data?.count ?? 0) / 24))}
      count={suggestions.data?.count ?? 0} pageSize={24} onChange={setPage} />
  </div>;
}
