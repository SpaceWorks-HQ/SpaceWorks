import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge, CollapsibleSection, ErrorBlock } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { ConsumablePoolCreateForm } from "./ConsumablePoolCreateForm";
import { poolLabel, poolQueryKey } from "./servicePools";

type Props = {
  makerspaceId: number;
  pools: PrinterPool[];
  existingPools: PrinterPool[];
  poolError: unknown;
  open: boolean;
  onToggle: () => void;
};

type StockState = {
  label: string;
  band: string;
  fill: string;
};

export function poolStockState(pool: PrinterPool): StockState {
  const remaining = Number(pool.remaining_grams);
  const threshold = pool.low_threshold_grams === null || pool.low_threshold_grams === undefined
    ? null
    : Number(pool.low_threshold_grams);
  if (remaining <= 0) {
    return { label: "Empty", band: "bg-danger text-bg", fill: "bg-danger" };
  }
  if (threshold !== null && remaining <= threshold) {
    return { label: "Low stock", band: "bg-warn text-on-warn", fill: "bg-warn" };
  }
  return { label: "In stock", band: "bg-success text-on-success", fill: "bg-success" };
}

export function SharedConsumablesSection({ makerspaceId, pools, existingPools, poolError, open, onToggle }: Props) {
  return (
    <CollapsibleSection title="Shared consumables" count={pools.length} open={open} onToggle={onToggle}>
      <div className="grid gap-4 p-3">
        <ConsumablePoolCreateForm makerspaceId={makerspaceId} existingPools={existingPools} />
        <section>
          <h4 className="title-section mb-2">Space-wide stock</h4>
          <ConsumablePoolList makerspaceId={makerspaceId} pools={pools} />
        </section>
        <ErrorBlock className="mt-2" error={poolError} />
      </div>
    </CollapsibleSection>
  );
}

export function ConsumablePoolList({ makerspaceId, pools }: { makerspaceId: number; pools: PrinterPool[] }) {
  const queryClient = useQueryClient();
  const [adjustingId, setAdjustingId] = useState<number | null>(null);
  const [quantityDelta, setQuantityDelta] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) });
  const adjustPool = useMutation({
    mutationFn: ({ id, quantity_delta }: { id: number; quantity_delta: string }) => staffRequest(`/admin/machine-service/consumable-pools/${id}/adjustments`, {
      method: "POST",
      body: JSON.stringify({ quantity_delta, reason: "Manual correction" }),
    }),
    onSuccess: async () => {
      setAdjustingId(null);
      setQuantityDelta("");
      await refresh();
    },
  });
  const visibility = useMutation({
    mutationFn: ({ id, isPublic }: { id: number; isPublic: boolean }) => staffRequest<PrinterPool>(`/admin/machine-service/consumable-pools/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_public: isPublic }),
    }),
    onSuccess: refresh,
  });

  return (
    <>
      <div className="grid gap-3">
        {pools.map((pool) => {
          const label = poolLabel(pool);
          const unit = pool.unit ?? "grams";
          const initial = Number(pool.initial_grams);
          const remaining = Number(pool.remaining_grams);
          const percent = initial > 0 ? Math.max(0, Math.min(100, (remaining / initial) * 100)) : 0;
          const state = poolStockState(pool);
          const isPublic = pool.is_public !== false;
          const isAdjusting = adjustingId === pool.id;
          const validAdjustment = quantityDelta.trim() !== "" && Number.isFinite(Number(quantityDelta)) && Number(quantityDelta) !== 0;
          return (
            <article className="overflow-hidden rounded-xl border border-line bg-bg" key={pool.id}>
              <div className={`flex items-center justify-between gap-2 px-3 py-1.5 font-mono text-xs font-semibold ${state.band}`}>
                <span>{state.label}</span>
                <span>{Math.round(percent)}% remaining</span>
              </div>
              <div className="grid gap-3 p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <strong className="text-sm text-ink">{label}</strong>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <Badge tone={pool.machine_id !== null ? "secondary" : pool.machine_type_id !== null ? "accent" : "neutral"}>
                        {pool.machine_id !== null ? "Machine-specific" : pool.machine_type_id !== null ? "Type-wide" : "Space-wide"}
                      </Badge>
                      <span className="chip">
                        <span
                          aria-hidden="true"
                          className="h-3 w-3 rounded-full border border-outline bg-surface"
                          style={pool.color_hex || pool.color ? { backgroundColor: pool.color_hex || pool.color } : undefined}
                        />
                        Colour: {pool.color || "Not specified"}
                      </span>
                      {!isPublic ? <Badge tone="warn">Hidden from requesters</Badge> : null}
                    </div>
                  </div>
                  {/* The accessible name must START with the visible text, or voice control cannot
                      act on what the user reads (WCAG 2.5.3 Label in Name) -- "click Public" has to
                      match. State lives in the label rather than aria-pressed: carrying both a
                      changing name and a pressed state double-signals the same fact. */}
                  <button
                    aria-label={`${isPublic ? "Public" : "Hidden"}: ${label} — activate to ${isPublic ? "hide from" : "show to"} requesters`}
                    className={isPublic ? "desk-button-warn" : "desk-button-success"}
                    disabled={visibility.isPending}
                    type="button"
                    onClick={() => visibility.mutate({ id: pool.id, isPublic: !isPublic })}
                  >
                    {isPublic ? "Public" : "Hidden"}
                  </button>
                </div>
                <div>
                  <div
                    aria-label={`${label} remaining`}
                    aria-valuemax={initial}
                    aria-valuemin={0}
                    aria-valuenow={remaining}
                    className="h-3 overflow-hidden rounded-full bg-surface"
                    role="progressbar"
                  >
                    <div className={`h-full rounded-full ${state.fill}`} style={{ width: `${percent}%` }} />
                  </div>
                  <p className="mt-1 font-mono text-sm text-muted">
                    <strong className="text-ink">{pool.remaining_grams}</strong> / {pool.initial_grams} {unit}
                  </p>
                </div>
                {isAdjusting ? (
                  <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); if (validAdjustment) adjustPool.mutate({ id: pool.id, quantity_delta: quantityDelta }); }}>
                    <label className="eyebrow grid min-w-48 flex-1 gap-1">
                      Adjustment ({unit}, + or −)
                      <input
                        autoFocus
                        className="desk-input"
                        inputMode="decimal"
                        step="any"
                        type="number"
                        value={quantityDelta}
                        onChange={(event) => setQuantityDelta(event.target.value)}
                        required
                      />
                    </label>
                    <button className="desk-button-primary" disabled={!validAdjustment || adjustPool.isPending} type="submit">
                      {adjustPool.isPending ? "Saving..." : "Save adjustment"}
                    </button>
                    <button className="desk-button-ghost" disabled={adjustPool.isPending} type="button" onClick={() => { setAdjustingId(null); setQuantityDelta(""); adjustPool.reset(); }}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <button className="desk-button-secondary justify-self-start" type="button" onClick={() => { setAdjustingId(pool.id); setQuantityDelta(""); adjustPool.reset(); }}>
                    Adjust stock
                  </button>
                )}
              </div>
            </article>
          );
        })}
        {!pools.length ? <p className="text-sm text-muted">No consumable pools.</p> : null}
      </div>
      <ErrorBlock className="mt-2" error={adjustPool.error ?? visibility.error} />
    </>
  );
}
