import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiPath } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import type { PaymentSummary } from "./PaymentReconcileActions";
import type { CustomFormSchema } from "../forms/customFormTypes";

export type EventStatus = "draft" | "published" | "cancelled" | "completed";
export type EventRegistrationStatus = "registered" | "waitlisted" | "cancelled" | "attended";
export type EventRegistrationCounts = Record<EventRegistrationStatus, number>;

export type StaffEvent = {
  id: number;
  makerspace_id: number;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  capacity: number;
  payment_amount: string;
  is_public: boolean;
  image_url: string | null;
  status: EventStatus;
  // Present on the admin serializer; needed by the staff registration form, which must
  // collect the same answers public self-registration does.
  custom_form: CustomFormSchema | null;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
  registration_counts: EventRegistrationCounts;
};

export type EventRegistration = {
  id: number;
  event_id: number;
  name: string;
  email: string;
  phone: string;
  status: EventRegistrationStatus;
  payment: PaymentSummary | null;
  created_at: string;
};

export type EventPayload = {
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  location: string;
  capacity: number;
  payment_amount: string;
  is_public: boolean;
};

export type EventPatch = Partial<EventPayload>;
export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };

const EVENT_LIST_PATH: ApiPath = "/api/v1/admin/makerspaces/{makerspace_id}/events/";
const EVENT_DETAIL_PATH: ApiPath = "/api/v1/admin/events/{id}/";
const EVENT_PUBLISH_PATH: ApiPath = "/api/v1/admin/events/{id}/publish/";
const EVENT_CANCEL_PATH: ApiPath = "/api/v1/admin/events/{id}/cancel/";
const EVENT_COMPLETE_PATH: ApiPath = "/api/v1/admin/events/{id}/complete/";
const EVENT_REGISTRATIONS_PATH: ApiPath = "/api/v1/admin/events/{id}/registrations/";
const MARK_ATTENDED_PATH: ApiPath = "/api/v1/admin/event-registrations/{id}/mark-attended/";

function staffPath(path: ApiPath, replacements: Record<string, number>) {
  return Object.entries(replacements).reduce(
    (value, [key, replacement]) => value.replace(`{${key}}`, String(replacement)),
    path.replace("/api/v1", ""),
  );
}

export const eventKeys = {
  all: (makerspaceId: number) => ["events", makerspaceId] as const,
  list: (makerspaceId: number) => [...eventKeys.all(makerspaceId), "list"] as const,
  detail: (eventId: number) => ["event", eventId] as const,
  registrations: (eventId: number) => ["event", eventId, "registrations"] as const,
};

export function useEvents(makerspaceId: number, page = 1) {
  return useQuery({ queryKey: [...eventKeys.list(makerspaceId), page], queryFn: () =>
    staffRequest<Paginated<StaffEvent>>(
      `${staffPath(EVENT_LIST_PATH, { makerspace_id: makerspaceId })}?page=${page}`,
    ) });
}

export function useEvent(eventId: number) {
  return useQuery({ queryKey: eventKeys.detail(eventId), queryFn: () =>
    staffRequest<StaffEvent>(staffPath(EVENT_DETAIL_PATH, { id: eventId })) });
}

export function useEventRegistrations(eventId: number, page = 1) {
  return useQuery({
    queryKey: [...eventKeys.registrations(eventId), page],
    queryFn: () => staffRequest<Paginated<EventRegistration>>(
      `${staffPath(EVENT_REGISTRATIONS_PATH, { id: eventId })}?page=${page}`,
    ),
  });
}

export function useEventInvalidation(makerspaceId: number, eventId?: number) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) });
    if (eventId !== undefined) await queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) });
  };
}

export function useCreateEvent(makerspaceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: EventPayload) => staffRequest<StaffEvent>(
      staffPath(EVENT_LIST_PATH, { makerspace_id: makerspaceId }),
      { method: "POST", body: JSON.stringify(payload) },
    ), onSuccess: async (created) => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(created.id) }),
    ]); },
  });
}

export function useUpdateEvent(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: EventPatch) => staffRequest<StaffEvent>(
      staffPath(EVENT_DETAIL_PATH, { id: eventId }),
      { method: "PATCH", body: JSON.stringify(payload) },
    ), onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    ]); },
  });
}

function useLifecycle(makerspaceId: number, eventId: number, path: ApiPath) {
  const invalidate = useEventInvalidation(makerspaceId, eventId);
  return useMutation({ mutationFn: () => staffRequest<StaffEvent>(staffPath(path, { id: eventId }), {
    method: "POST", body: JSON.stringify({}),
  }), onSuccess: invalidate });
}

export function usePublishEvent(makerspaceId: number, eventId: number) {
  return useLifecycle(makerspaceId, eventId, EVENT_PUBLISH_PATH);
}
export function useCancelEvent(makerspaceId: number, eventId: number) {
  return useLifecycle(makerspaceId, eventId, EVENT_CANCEL_PATH);
}
export function useCompleteEvent(makerspaceId: number, eventId: number) {
  return useLifecycle(makerspaceId, eventId, EVENT_COMPLETE_PATH);
}

export function useMarkEventAttended(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (registrationId: number) => staffRequest<EventRegistration>(
      staffPath(MARK_ATTENDED_PATH, { id: registrationId }),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    ]); },
  });
}

export type EventEligibleMember = { member_id: number; display_name: string };

const ELIGIBLE_MEMBERS_PATH: ApiPath = "/api/v1/admin/events/{id}/eligible-members/";

export function eligibleMemberKey(eventId: number) {
  return ["event", eventId, "eligible-members"] as const;
}

/**
 * The roster the staff registration picker reads. Hung off the event, so it inherits
 * the event's own permission check rather than introducing a second answer to "who may
 * see this makerspace's members".
 */
export function useEventEligibleMembers(eventId: number, enabled = true) {
  return useQuery({
    queryKey: eligibleMemberKey(eventId),
    queryFn: () => staffRequest<EventEligibleMember[]>(
      staffPath(ELIGIBLE_MEMBERS_PATH, { id: eventId }),
    ),
    enabled,
  });
}

export function useRegisterMemberForEvent(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      member_id: number;
      phone?: string;
      custom_answers?: Record<string, unknown>;
    }) =>
      staffRequest<EventRegistration>(
        staffPath(EVENT_REGISTRATIONS_PATH, { id: eventId }),
        { method: "POST", body: JSON.stringify(payload) },
      ),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
      // The picker must forget the person it just registered, or they can be picked
      // again and the second attempt only ever returns a duplicate error.
      queryClient.invalidateQueries({ queryKey: eligibleMemberKey(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    ]); },
  });
}
