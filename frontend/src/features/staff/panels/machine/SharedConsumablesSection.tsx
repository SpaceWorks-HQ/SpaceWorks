import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { CollapsibleSection } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { poolLabel, poolPath, poolQueryKey, type PoolUnit } from "./servicePools";

type Props = {
  makerspaceId: number;
  pools: PrinterPool[];
  poolError: unknown;
  open: boolean;
  onToggle: () => void;
};

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const blankPool = { material: "", color: "", brand: "", quantity: "", unit: "grams" as PoolUnit, low_threshold_grams: "" };

export function SharedConsumablesSection({ makerspaceId, pools, poolError, open, onToggle }: Props) {
  const queryClient = useQueryClient();
  const [pool, setPool] = useState(blankPool);
  const createPool = useMutation({
    mutationFn: () => staffRequest<PrinterPool>(poolPath(makerspaceId), {
      method: "POST",
      body: JSON.stringify({
        material: pool.material.trim(),
        color: pool.color.trim(),
        brand: pool.brand.trim(),
        quantity: pool.quantity,
        unit: pool.unit,
        low_threshold_grams: pool.unit === "grams" && pool.low_threshold_grams ? pool.low_threshold_grams : null,
      }),
    }),
    onSuccess: () => {
      setPool(blankPool);
      void queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) });
    },
  });

  return (
    <CollapsibleSection title="Shared consumables" count={pools.length} open={open} onToggle={onToggle}>
      <div className="grid gap-4 p-3">
        <section>
          <h4 className="title-section mb-2">Create shared pool</h4>
          <div className="grid gap-2 md:grid-cols-6">
            <input aria-label="Material" className={`desk-input ${focusRing}`} placeholder="Material" value={pool.material} onChange={(event) => setPool({ ...pool, material: event.target.value })} />
            <input aria-label="Colour" className={`desk-input ${focusRing}`} placeholder="Colour" value={pool.color} onChange={(event) => setPool({ ...pool, color: event.target.value })} />
            <input aria-label="Brand" className={`desk-input ${focusRing}`} placeholder="Brand" value={pool.brand} onChange={(event) => setPool({ ...pool, brand: event.target.value })} />
            <select aria-label="Pool unit" className={`desk-input ${focusRing}`} value={pool.unit} onChange={(event) => setPool({ ...pool, unit: event.target.value as PoolUnit })}>
              <option value="grams">Grams</option>
              <option value="milliliters">Milliliters</option>
              <option value="millimeters">Millimeters</option>
              <option value="count">Count</option>
            </select>
            <input aria-label="Initial quantity" className={`desk-input ${focusRing}`} type="number" min="0" placeholder="Initial quantity" value={pool.quantity} onChange={(event) => setPool({ ...pool, quantity: event.target.value })} />
            <button className="desk-button-primary" disabled={!pool.material.trim() || !pool.quantity || createPool.isPending} onClick={() => createPool.mutate()}>Add pool</button>
          </div>
          {pool.unit === "grams" ? <input aria-label="Low threshold grams" className={`desk-input ${focusRing} mt-2 md:max-w-xs`} type="number" min="0" placeholder="Low threshold grams (optional)" value={pool.low_threshold_grams} onChange={(event) => setPool({ ...pool, low_threshold_grams: event.target.value })} /> : null}
        </section>
        <section>
          <h4 className="title-section mb-2">Shared pool stock</h4>
          <ConsumablePoolList makerspaceId={makerspaceId} pools={pools} />
        </section>
        <ErrorBlock error={poolError ?? createPool.error} />
      </div>
    </CollapsibleSection>
  );
}

export function ConsumablePoolList({ makerspaceId, pools }: { makerspaceId: number; pools: PrinterPool[] }) {
  const queryClient = useQueryClient();
  const adjustPool = useMutation({
    mutationFn: ({ id, quantity_delta }: { id: number; quantity_delta: string }) => staffRequest(`/admin/machine-service/consumable-pools/${id}/adjustments`, {
      method: "POST",
      body: JSON.stringify({ quantity_delta, reason: "Manual correction" }),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) }),
  });
  const adjust = (pool: PrinterPool) => {
    const unit = pool.unit ?? "grams";
    const quantityDelta = prompt(`Adjustment in ${unit} (+/-)`);
    if (quantityDelta !== null) adjustPool.mutate({ id: pool.id, quantity_delta: quantityDelta });
  };

  return (
    <>
      <div className="grid gap-2">
        {pools.map((pool) => (
          <div className="flex items-center justify-between rounded-md border border-line p-2" key={pool.id}>
            <span>{poolLabel(pool)} · {pool.remaining_grams} {pool.unit ?? "grams"}</span>
            <button className="desk-button-primary" disabled={adjustPool.isPending} onClick={() => adjust(pool)}>Adjust</button>
          </div>
        ))}
        {!pools.length ? <p className="text-sm text-muted">No consumable pools.</p> : null}
      </div>
      <ErrorBlock error={adjustPool.error} />
    </>
  );
}

function ErrorBlock({ error }: { error: unknown }) {
  return error instanceof Error ? <p className="text-sm text-danger">{error.message}</p> : null;
}
