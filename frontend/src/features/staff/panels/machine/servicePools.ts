import type { PrinterPool } from "../../../../generated/api";
import type { MeteringUnit } from "../../machinesApi";

export type PoolUnit = "grams" | "milliliters" | "millimeters" | "count";

export const poolQueryKey = (makerspaceId: number) => ["machine-service-pools", makerspaceId];
export const poolPath = (makerspaceId: number) =>
  `/admin/makerspaces/${makerspaceId}/machine-service/consumable-pools`;

export const unitLabels: Record<MeteringUnit, string> = {
  weight: "grams",
  volume: "milliliters",
  length: "millimeters",
  count: "count",
  minutes: "minutes",
};

export const poolUnits: Partial<Record<MeteringUnit, PoolUnit>> = {
  weight: "grams",
  volume: "milliliters",
  length: "millimeters",
  count: "count",
};

export function poolHasUnit(pool: PrinterPool, unit: PoolUnit) {
  return pool.unit === unit || (!pool.unit && unit === "grams");
}

export function usablePools(
  pools: PrinterPool[],
  unit: PoolUnit | undefined,
  machineId: string,
) {
  if (!unit) return [];
  const selectedId = Number(machineId);
  return pools.filter((pool) =>
    poolHasUnit(pool, unit) &&
    (pool.machine_id === null || (!!selectedId && pool.machine_id === selectedId)),
  );
}

export function poolLabel(pool: PrinterPool) {
  return [pool.brand, pool.material, pool.color].filter(Boolean).join(" ");
}
