import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews } from "../queryInvalidation";
import { Panel, type Makerspace, useStaffGet } from "./shared";

type ShelfItem = {
  id: number;
  name: string;
  needs_fix_quantity: number;
  available_quantity: number;
  total_quantity: number;
};

// The to-be-fixed shelf: items with units pulled out for repair (rejected as broken at
// handover). Staff can repair them back into stock or scrap them out of inventory.
export function NeedsFixShelf({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const shelf = useStaffGet<{ results: ShelfItem[] }>(
    ["needs-fix-shelf", makerspace.id],
    `/admin/inventory/needs-fix?makerspace=${makerspace.id}`,
  );
  const [qty, setQty] = useState<Record<number, string>>({});
  const [error, setError] = useState("");

  const act = useMutation({
    mutationFn: ({ id, action, quantity }: { id: number; action: "repair" | "scrap"; quantity: number }) =>
      staffRequest(`/admin/inventory/${id}/needs-fix`, {
        method: "POST",
        body: JSON.stringify({ action, quantity }),
      }),
    onSuccess: () => {
      setError("");
      queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
      invalidateInventoryViews(queryClient, makerspace.id);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Action failed."),
  });

  const rows = shelf.data?.results ?? [];
  const run = (item: ShelfItem, action: "repair" | "scrap") => {
    const quantity = Number(qty[item.id]) || item.needs_fix_quantity;
    act.mutate({ id: item.id, action, quantity });
  };

  return (
    <Panel title="To-be-fixed shelf">
      <p className="mb-3 text-sm text-muted">
        Units rejected as broken at handover. Repair to return them to available stock, or
        scrap to remove them from inventory.
      </p>
      {shelf.isLoading ? <p className="text-sm text-muted">Loading shelf...</p> : null}
      {!shelf.isLoading && !rows.length ? (
        <p className="text-sm text-muted">Nothing on the shelf - no items awaiting repair.</p>
      ) : null}
      <div className="grid gap-2">
        {rows.map((item) => (
          <div key={item.id} className="rounded-md border border-line bg-surface px-3 py-2">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="font-medium text-ink">{item.name}</span>
              <span className="rounded-md bg-warn/15 px-2 py-0.5 text-xs font-semibold text-warn-ink">
                {item.needs_fix_quantity} to fix
              </span>
              <span className="font-mono text-muted">{item.available_quantity} available · {item.total_quantity} total</span>
            </div>
            <div className="desk-actions mt-2 flex flex-wrap items-end gap-2">
              <label className="eyebrow grid gap-1">
                <span>Quantity</span>
                <input
                  className="desk-input w-24"
                  type="number"
                  min="1"
                  max={item.needs_fix_quantity}
                  placeholder={String(item.needs_fix_quantity)}
                  value={qty[item.id] ?? ""}
                  onChange={(event) => setQty((current) => ({ ...current, [item.id]: event.target.value }))}
                />
              </label>
              <button className="desk-button-success" type="button" disabled={act.isPending} onClick={() => run(item, "repair")}>
                Move back to inventory
              </button>
              <button type="button" className="desk-button-danger" disabled={act.isPending} onClick={() => run(item, "scrap")}>
                Scrap
              </button>
            </div>
          </div>
        ))}
      </div>
      {error ? <p className="mt-2 text-sm text-danger">{error}</p> : null}
      {shelf.error instanceof Error ? <p className="mt-2 text-sm text-danger">{shelf.error.message}</p> : null}
    </Panel>
  );
}
