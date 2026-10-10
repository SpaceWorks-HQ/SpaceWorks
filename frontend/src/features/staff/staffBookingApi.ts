import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { CustomAnswers } from "../forms/customFormTypes";
import { bookingKeys, type Booking, type Paginated } from "./bookingsApi";

export type StaffBookingPayload = {
  member_id: number;
  starts_at: string;
  ends_at: string;
  note: string;
  certification_override_reason?: string;
  custom_answers?: CustomAnswers;
};

export function getBookingMachineTypes(makerspaceId: number, page: number) {
  return staffRequest<Paginated<{ id: number; name: string }>>(
    `/admin/makerspaces/${makerspaceId}/booking-machine-types/?page=${page}`,
  );
}

export function useBookingEligibleMembers(spaceId: number, page: number) {
  return useQuery({
    queryKey: ["booking-eligible-members", spaceId, page],
    queryFn: () => staffRequest<Paginated<{ member_id: number; display_name: string }>>(
      `/admin/spaces/${spaceId}/eligible-members/?page=${page}`,
    ),
  });
}

export function useStaffCreateBooking(makerspaceId: number, spaceId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: StaffBookingPayload) => staffRequest<Booking>(
      `/admin/spaces/${spaceId}/bookings/`, { method: "POST", body: JSON.stringify(payload) },
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: bookingKeys.spaces(makerspaceId) }),
        queryClient.invalidateQueries({ queryKey: bookingKeys.bookings(spaceId) }),
        queryClient.invalidateQueries({ queryKey: ["public-space-availability"] }),
        queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
      ]);
    },
  });
}
