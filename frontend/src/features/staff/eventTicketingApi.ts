import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { staffRequest } from "../../lib/api";
import type { Paginated } from "./eventsApiTypes";

export type EventCode = {
  id: number; max_uses: number; uses: number; expires_at: string | null;
  revoked_at: string | null; code?: string;
};
export type EventPromo = EventCode & { percent_off: number; amount_off: string };
export type StaffTicket = {
  id: number; name: string; amount: string; audience: "member" | "public";
  capacity: number; sales_start_at: string | null; sales_end_at: string | null;
};

export function useEventTicketing<T>(eventId: number, kind: "invites" | "promo-codes" | "ticket-types", page = 1) {
  const client = useQueryClient();
  const key = ["event", eventId, kind];
  const path = `/admin/events/${eventId}/${kind}/`;
  const rows = useQuery({ queryKey: [...key, page], queryFn: () => staffRequest<Paginated<T>>(`${path}?page=${page}`) });
  const refresh = () => Promise.all([
    client.invalidateQueries({ queryKey: key }),
    client.invalidateQueries({ queryKey: ["public-events"] }),
    client.invalidateQueries({ queryKey: ["public-event"] }),
  ]);
  const create = useMutation({ mutationFn: (payload: Record<string, unknown>) => staffRequest<T>(path, { method: "POST", body: JSON.stringify(payload) }), onSuccess: refresh });
  const revoke = useMutation({
    mutationFn: (id: number) => staffRequest<T>(`/admin/${kind === "invites" ? "event-invites" : "event-promos"}/${id}/revoke/`, { method: "POST", body: "{}" }),
    onSuccess: refresh,
  });
  return { rows, create, revoke };
}

/** Select controls need all options while the API retains its normal pagination. */
export async function eventOptions<T>(path: string): Promise<T[]> {
  const result: T[] = [];
  for (let page = 1; ; page += 1) {
    const response = await staffRequest<Paginated<T>>(`${path}?page=${page}`);
    result.push(...response.results);
    if (!response.next) return result;
  }
}
