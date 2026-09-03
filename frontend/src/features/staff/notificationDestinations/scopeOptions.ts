import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../../lib/api";

export type ScopeOption = { id: number; name: string };

export type ScopeOptions = {
  machineTypes: ScopeOption[];
  machines: ScopeOption[];
  categories: ScopeOption[];
};

/**
 * Scope targets a room or rule can name. Each list is optional — a makerspace with no
 * machines simply gets no machine column rather than an empty picker.
 */
export function useScopeOptions(makerspaceId: number, enabled = true): ScopeOptions {
  const machineTypes = useQuery({
    queryKey: ["machine-types", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machine-types`,
      ).catch(() => []),
    enabled,
  });
  const machines = useQuery({
    queryKey: ["machines", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/machines`,
      ).catch(() => []),
    enabled,
  });
  const categories = useQuery({
    queryKey: ["categories", makerspaceId, "scope"],
    queryFn: () =>
      staffRequest<{ results?: { id: number; name: string }[] } | { id: number; name: string }[]>(
        `/admin/makerspace/${makerspaceId}/categories`,
      ).catch(() => []),
    enabled,
  });

  return {
    machineTypes: unwrap(machineTypes.data),
    machines: unwrap(machines.data),
    categories: unwrap(categories.data),
  };
}

function unwrap(value: unknown): ScopeOption[] {
  if (Array.isArray(value)) return value as ScopeOption[];
  if (value && typeof value === "object" && Array.isArray((value as { results?: unknown }).results)) {
    return (value as { results: ScopeOption[] }).results;
  }
  return [];
}
