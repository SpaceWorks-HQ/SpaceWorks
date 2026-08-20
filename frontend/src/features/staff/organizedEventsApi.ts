import { useQuery } from "@tanstack/react-query";

import type { ApiPath, EventListResponse } from "../../generated/api";
import { staffRequest } from "../../lib/api";

const ORGANIZED_EVENTS_PATH: ApiPath = "/api/v1/admin/organized-events/";

function staffPath(path: ApiPath) {
  return path.replace("/api/v1", "");
}

export type { EventAdmin, EventListResponse } from "../../generated/api";

export const organizedEventKeys = {
  all: ["events", "organized"] as const,
  list: (page: number, pageSize: number) =>
    [...organizedEventKeys.all, "list", page, pageSize] as const,
};

export function useOrganizedEvents(page: number, pageSize = 50) {
  return useQuery({
    queryKey: organizedEventKeys.list(page, pageSize),
    queryFn: () => staffRequest<EventListResponse>(
      `${staffPath(ORGANIZED_EVENTS_PATH)}?page=${page}&page_size=${pageSize}`,
    ),
  });
}
