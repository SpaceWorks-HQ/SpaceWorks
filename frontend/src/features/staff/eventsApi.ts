import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiPath } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import { organizedEventKeys } from "./organizedEventsApi";
import {
  CHECK_IN_RESOLVE_PATH,
  EVENT_CANCEL_PATH,
  EVENT_COMPLETE_PATH,
  EVENT_DETAIL_PATH,
  EVENT_LIST_PATH,
  EVENT_PUBLISH_PATH,
  eventKeys,
  staffPath,
  type EventPatch,
  type EventPayload,
  type EventRegistrationStatus,
  type Paginated,
  type StaffEvent,
} from "./eventsApiTypes";

export {
  eligibleMemberKey,
  eventKeys,
  type EventPatch,
  type EventPayload,
  type EventRegistration,
  type EventRegistrationCounts,
  type EventRegistrationStatus,
  type EventStatus,
  type Paginated,
  type StaffEvent,
} from "./eventsApiTypes";
export {
  useApproveEventRegistration,
  useEventEligibleMembers,
  useEventRegistrations,
  useMarkEventAttended,
  usePromoteEventRegistration,
  useRegisterMemberForEvent,
  useRejectEventRegistration,
  type EventEligibleMember,
} from "./eventsRegistrationApi";

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

export function useEventInvalidation(makerspaceId: number, eventId?: number) {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
      queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
      ...(eventId === undefined ? [] : [
        queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      ]),
    ]);
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
      queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
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
      queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
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

export type EventCheckInResolution = {
  registration_id: number;
  name: string;
  status: EventRegistrationStatus;
  // Null when the event is free or no charge was raised. Shown to the staffer, never
  // used to block: cash is taken at the door and reconciled later.
  payment_status: string | null;
  // Reported, never enforced -- someone with missing evidence is exactly who the host wants
  // to hand a waiver to at the desk; not_required means the host has no active waiver.
  host_waiver_state: "not_required" | "on_file" | "missing";
  event_status: string;
  confirmable: boolean;
};

export function useResolveEventCheckIn(eventId: number) {
  // No invalidation: resolving is read-only by design. It turns a scanned token into a
  // name so the staffer can see who is in front of them; `useMarkEventAttended` is the
  // separate, explicitly-confirmed mutation.
  return useMutation({
    mutationFn: (checkinToken: string) => staffRequest<EventCheckInResolution>(
      staffPath(CHECK_IN_RESOLVE_PATH, { id: eventId }),
      { method: "POST", body: JSON.stringify({ checkin_token: checkinToken }) },
    ),
  });
}
