import { useQuery } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";

export function useUnreadNotifications(makerspaceId: number | undefined, enabled: boolean) {
  const query = useQuery({
    queryKey: ["notifications-unread", makerspaceId],
    queryFn: () => staffRequest<{ count: number }>(`/notifications/makerspace/${makerspaceId}/unread-count`),
    enabled: enabled && Boolean(makerspaceId),
    refetchInterval: 60_000,
    retry: false,
  });

  if (query.isError) return 0;
  return Math.max(0, query.data?.count ?? 0);
}
