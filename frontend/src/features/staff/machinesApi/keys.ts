import type { MachineCollection } from "./types";

export const machineKeys = {
  all: ["machines"] as const,
  list: (makerspaceId: number) => ["machines", makerspaceId] as const,
  types: (makerspaceId: number) => ["machine-types", makerspaceId] as const,
  pricing: (makerspaceId: number) => ["machine-type-pricing", makerspaceId] as const,
  detail: (machineId: number) => ["machine", machineId] as const,
  usage: (machineId: number) => ["machine-usage", machineId] as const,
  operators: (machineId: number) => ["machine-operators", machineId] as const,
  operatorCandidates: (machineId: number) => ["machine-operator-candidates", machineId] as const,
  consumables: (machineId: number) => ["machine-consumables", machineId] as const,
  consumableCandidates: (machineId: number) => ["machine-consumable-candidates", machineId] as const,
  documents: (machineId: number) => ["machine-documents", machineId] as const,
  errors: (machineId: number) => ["machine-errors", machineId] as const,
};

export function collectionResults<T>(data: MachineCollection<T> | undefined): T[] {
  if (!data) return [];
  return Array.isArray(data) ? data : data.results;
}

export const machinePublicPreviewKey = (machineId: number) =>
  ['machine-public-preview', machineId] as const;
