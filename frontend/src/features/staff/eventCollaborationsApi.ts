import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type {
  ApiPath,
  EventCollaborationInbox as ApiEventCollaborationInbox,
  EventCollaborator as ApiEventCollaborator,
} from "../../generated/api";
import { staffRequest } from "../../lib/api";
import { eventKeys } from "./eventsApi";
import { organizedEventKeys } from "./organizedEventsApi";

const COLLABORATORS_PATH: ApiPath = "/api/v1/admin/events/{id}/collaborators/";
const COLLABORATION_REMOVE_PATH: ApiPath = "/api/v1/admin/event-collaborations/{id}/remove/";
const COLLABORATION_INBOX_PATH: ApiPath = "/api/v1/admin/makerspaces/{makerspace_id}/event-collaborations/";
const COLLABORATION_RESPOND_PATH: ApiPath = "/api/v1/admin/event-collaborations/{id}/respond/";

function staffPath(path: ApiPath, replacements: Record<string, number>) {
  return Object.entries(replacements).reduce(
    (value, [key, replacement]) => value.replace(`{${key}}`, String(replacement)),
    path.replace("/api/v1", ""),
  );
}

export type { EventCollaborator, EventCollaborationInbox } from "../../generated/api";

export const collaborationKeys = {
  forEvent: (eventId: number) => ["event", eventId, "collaborators"] as const,
  inbox: (makerspaceId: number) => ["events", makerspaceId, "collaboration-inbox"] as const,
};

export function useEventCollaborators(eventId: number) {
  return useQuery({
    queryKey: collaborationKeys.forEvent(eventId),
    queryFn: () => staffRequest<ApiEventCollaborator[]>(
      staffPath(COLLABORATORS_PATH, { id: eventId }),
    ),
  });
}

export function useReplaceEventCollaborators(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    // PUT replaces the whole set -- a merge would make removal inexpressible -- so callers
    // send the full intended slug list, not a delta.
    mutationFn: (slugs: string[]) => staffRequest<ApiEventCollaborator[]>(
      staffPath(COLLABORATORS_PATH, { id: eventId }),
      { method: "PUT", body: JSON.stringify({ slugs }) },
    ),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: collaborationKeys.forEvent(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
      queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
    ]); },
  });
}

export function useRemoveEventCollaborator(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    // The dedicated remove endpoint, not the replacing PUT: rebuilding the set revalidates
    // every remaining slug and would fail because an unrelated partner had been archived.
    mutationFn: (collaborationId: number) => staffRequest<void>(
      staffPath(COLLABORATION_REMOVE_PATH, { id: collaborationId }),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: collaborationKeys.forEvent(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
      queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
    ]); },
  });
}

export function useCollaborationInbox(makerspaceId: number) {
  return useQuery({
    queryKey: collaborationKeys.inbox(makerspaceId),
    queryFn: () => staffRequest<ApiEventCollaborationInbox[]>(
      staffPath(COLLABORATION_INBOX_PATH, { makerspace_id: makerspaceId }),
    ),
    retry: false,
  });
}

export function useRespondToCollaboration(makerspaceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, accept }: { id: number; accept: boolean }) =>
      staffRequest<ApiEventCollaborator>(
        staffPath(COLLABORATION_RESPOND_PATH, { id }),
        { method: "POST", body: JSON.stringify({ accept }) },
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: collaborationKeys.inbox(makerspaceId) });
    },
  });
}
