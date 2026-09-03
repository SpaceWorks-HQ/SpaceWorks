import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { CustomFormSchema } from "../forms/customFormTypes";
import { eventKeys, type Paginated, type StaffEvent } from "./eventsApi";
import { organizedEventKeys } from "./organizedEventsApi";

export type EventSeriesStatus = "draft" | "published" | "cancelled" | "completed";
export type EventSeriesPayload = {
  title: string;
  description: string;
  location: string;
  location_kind: "indoor" | "outdoor" | "other";
  custom_form: CustomFormSchema;
  capacity: number;
  payment_amount: string;
  registration_requires_approval: boolean;
  registration_cutoff_lead_minutes: number | null;
  is_public: boolean;
  recurrence_timezone: string;
  dtstart_local_date: string;
  dtstart_local_time: string;
  recurrence_rule: string;
  duration_minutes: number;
  effective_from?: string;
};
export type EventSeries = Omit<EventSeriesPayload, "effective_from"> & {
  id: number;
  public_token: string;
  makerspace_id: number;
  status: EventSeriesStatus;
  revision: number;
  next_occurrence_at: string | null;
  future_occurrence_count: number;
  last_materialized_at: string | null;
  last_generation_error_code: string;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
  image_url: string | null;
};
type MutationResponse = {
  series: EventSeries;
  created_occurrence_ids: number[];
  removed_occurrence_ids: number[];
  affected_count: number;
};

export const eventSeriesKeys = {
  list: (makerspaceId: number) => ["event-series", makerspaceId] as const,
  detail: (seriesId: number) => ["event-series", seriesId, "detail"] as const,
  occurrences: (seriesId: number) => ["event-series", seriesId, "occurrences"] as const,
  collaborators: (seriesId: number) => ["event-series", seriesId, "collaborators"] as const,
};

function base(makerspaceId: number) {
  return `/admin/makerspaces/${makerspaceId}/event-series/`;
}
function detail(seriesId: number) {
  return `/admin/event-series/${seriesId}/`;
}

export function useEventSeriesList(makerspaceId: number) {
  return useQuery({
    queryKey: eventSeriesKeys.list(makerspaceId),
    queryFn: () => staffRequest<Paginated<EventSeries>>(base(makerspaceId)),
  });
}
export function useEventSeries(seriesId: number) {
  return useQuery({
    queryKey: eventSeriesKeys.detail(seriesId),
    queryFn: () => staffRequest<EventSeries>(detail(seriesId)),
  });
}
export function useEventSeriesOccurrences(seriesId: number) {
  return useQuery({
    queryKey: eventSeriesKeys.occurrences(seriesId),
    queryFn: () => staffRequest<Paginated<StaffEvent>>(`${detail(seriesId)}occurrences/`),
  });
}

function useInvalidate(makerspaceId: number, seriesId?: number) {
  const client = useQueryClient();
  return async () => Promise.all([
    client.invalidateQueries({ queryKey: eventSeriesKeys.list(makerspaceId) }),
    client.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    client.invalidateQueries({ queryKey: organizedEventKeys.all }),
    client.invalidateQueries({ queryKey: ["public-events"] }),
    client.invalidateQueries({ queryKey: ["member"] }),
    ...(seriesId ? [
      client.invalidateQueries({ queryKey: eventSeriesKeys.detail(seriesId) }),
      client.invalidateQueries({ queryKey: eventSeriesKeys.occurrences(seriesId) }),
    ] : []),
  ]);
}

export function useCreateEventSeries(makerspaceId: number) {
  const invalidate = useInvalidate(makerspaceId);
  return useMutation({
    mutationFn: (payload: EventSeriesPayload) => staffRequest<MutationResponse>(base(makerspaceId), {
      method: "POST", body: JSON.stringify(payload),
    }),
    onSuccess: invalidate,
  });
}
export function useUpdateEventSeries(makerspaceId: number, seriesId: number) {
  const invalidate = useInvalidate(makerspaceId, seriesId);
  return useMutation({
    mutationFn: (payload: Partial<EventSeriesPayload>) => staffRequest<MutationResponse>(detail(seriesId), {
      method: "PATCH", body: JSON.stringify(payload),
    }),
    onSuccess: invalidate,
  });
}
export function useEventSeriesAction(makerspaceId: number, seriesId: number, action: "publish" | "cancel" | "complete" | "extend") {
  const invalidate = useInvalidate(makerspaceId, seriesId);
  return useMutation({
    mutationFn: () => staffRequest<MutationResponse>(`${detail(seriesId)}${action}/`, {
      method: "POST", body: JSON.stringify({}),
    }),
    onSuccess: invalidate,
  });
}
