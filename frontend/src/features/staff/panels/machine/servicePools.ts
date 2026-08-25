import type { PrinterPool } from "../../../../generated/api";
import type { Machine, MeteringUnit } from "../../machinesApi";

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
  machines: Machine[],
  makerspaceId: number,
) {
  if (!unit) return [];
  const selectedId = Number(machineId);
  const machine = machines.find((candidate) => candidate.id === selectedId && candidate.makerspace === makerspaceId);
  if (!machine) return [];
  return pools.filter((pool) =>
    poolHasUnit(pool, unit) &&
    (
      pool.machine_id === machine.id ||
      (
        pool.machine_id === null &&
        (pool.machine_type_id === null || pool.machine_type_id === machine.machine_type.id)
      )
    ),
  );
}

export function poolLabel(pool: PrinterPool) {
  return [pool.brand, pool.material, pool.color].filter(Boolean).join(" ");
}
