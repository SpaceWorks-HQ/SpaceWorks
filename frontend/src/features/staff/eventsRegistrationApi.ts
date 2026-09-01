import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import { organizedEventKeys } from "./organizedEventsApi";
import {
  ELIGIBLE_MEMBERS_PATH,
  EVENT_REGISTRATIONS_PATH,
  MARK_ATTENDED_PATH,
  eligibleMemberKey,
  eventKeys,
  staffPath,
  type EventRegistration,
  type Paginated,
} from "./eventsApiTypes";

const APPROVE_PATH = "/api/v1/admin/event-registrations/{id}/approve/";
const REJECT_PATH = "/api/v1/admin/event-registrations/{id}/reject/";
const PROMOTE_PATH = "/api/v1/admin/event-registrations/{id}/promote/";

export function useEventRegistrations(eventId: number, page = 1) {
  return useQuery({
    queryKey: [...eventKeys.registrations(eventId), page],
    queryFn: () => staffRequest<Paginated<EventRegistration>>(
      `${staffPath(EVENT_REGISTRATIONS_PATH, { id: eventId })}?page=${page}`,
    ),
  });
}

function useRegistrationAction(
  makerspaceId: number,
  eventId: number,
  path: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (registrationId: number) => staffRequest<EventRegistration>(
      staffPath(path, { id: registrationId }),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
        queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
        queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
      ]);
    },
  });
}

export function useMarkEventAttended(makerspaceId: number, eventId: number) {
  return useRegistrationAction(makerspaceId, eventId, MARK_ATTENDED_PATH);
}

export function useApproveEventRegistration(makerspaceId: number, eventId: number) {
  return useRegistrationAction(makerspaceId, eventId, APPROVE_PATH);
}

export function useRejectEventRegistration(makerspaceId: number, eventId: number) {
  return useRegistrationAction(makerspaceId, eventId, REJECT_PATH);
}

export function usePromoteEventRegistration(makerspaceId: number, eventId: number) {
  return useRegistrationAction(makerspaceId, eventId, PROMOTE_PATH);
}

export type EventEligibleMember = { member_id: number; display_name: string };

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
      email?: string;
      custom_answers?: Record<string, unknown>;
    }) => staffRequest<EventRegistration>(
      staffPath(EVENT_REGISTRATIONS_PATH, { id: eventId }),
      { method: "POST", body: JSON.stringify(payload) },
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
        queryClient.invalidateQueries({ queryKey: eligibleMemberKey(eventId) }),
        queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
        queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
      ]);
    },
  });
}
