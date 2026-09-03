import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest, staffRequestBlob } from "../../lib/api";
import { eventKeys } from "./eventsApiTypes";

export type BadgeTemplate = {
  version: number;
  paper_size: "A4" | "LETTER" | "custom";
  orientation: "portrait" | "landscape";
  page_width_mm: number | null;
  page_height_mm: number | null;
  card_width_mm: number;
  card_height_mm: number;
  margin_mm: number;
  gap_mm: number;
  template: "standard";
  fields: string[];
  font_size_pt: number;
  name_font_size_pt: number;
  text_align: "left" | "center";
  include_qr: boolean;
};

export function useEventBadgeTemplate(eventId: number) {
  return useQuery({
    queryKey: eventKeys.badgeTemplate(eventId),
    queryFn: () => staffRequest<BadgeTemplate>(`/admin/events/${eventId}/badge-template/`),
  });
}

export function useSaveEventBadgeTemplate(makerspaceId: number, eventId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (template: BadgeTemplate) => staffRequest<BadgeTemplate>(
      `/admin/events/${eventId}/badge-template/`,
      { method: "PUT", body: JSON.stringify(template) },
    ),
    onSuccess: async () => Promise.all([
      queryClient.invalidateQueries({ queryKey: eventKeys.badgeTemplate(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    ]),
  });
}

export function useGenerateEventBadges(eventId: number) {
  return useMutation({
    mutationFn: (payload: { registration_ids: number[]; include_attended: boolean }) =>
      staffRequestBlob(`/admin/events/${eventId}/badges.pdf`, {
        method: "POST", body: JSON.stringify(payload),
      }),
  });
}
