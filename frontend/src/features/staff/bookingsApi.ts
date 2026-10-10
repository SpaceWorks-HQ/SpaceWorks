import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiPath } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import type { CustomAnswerSnapshot, CustomFormSchema } from "../forms/customFormTypes";
import type { PaymentSummary } from "./PaymentReconcileActions";

export type BookingStatus = "pending" | "confirmed" | "rejected" | "cancelled" | "completed" | "no_show";
export type BookableSpace = {
  id: number;
  public_token: string;
  makerspace_id: number;
  name: string;
  kind: "dev_room" | "bench" | "meeting" | "other";
  description: string;
  capacity: number;
  location: string;
  image_url: string;
  is_public: boolean;
  show_public_availability: boolean;
  show_public_booker_names: boolean;
  approval_mode: "instant" | "approve";
  payment_amount: string;
  custom_form: CustomFormSchema;
  requester_notifications_enabled: boolean | null;
  machine_type?: number | null;
  effective_requester_notifications_enabled: boolean;
  is_active: boolean;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
};

export type BookableSpacePayload = Pick<BookableSpace,
  "name" | "kind" | "description" | "capacity" | "location" | "is_public" |
  "show_public_availability" | "show_public_booker_names" | "approval_mode" |
  "custom_form" | "requester_notifications_enabled" | "payment_amount" | "machine_type"
>;

export type Booking = {
  id: number;
  public_token: string;
  space_id: number;
  name: string;
  email: string;
  phone: string;
  starts_at: string;
  ends_at: string;
  status: BookingStatus;
  note: string;
  custom_answers: CustomAnswerSnapshot | null;
  payment: PaymentSummary | null;
  created_at: string;
};

export type Paginated<T> = { count: number; next: string | null; previous: string | null; results: T[] };
export type BookingFilters = { status?: BookingStatus | ""; starts_at?: string; ends_at?: string; booking_id?: number };

const SPACE_LIST_PATH: ApiPath = "/api/v1/admin/makerspaces/{makerspace_id}/spaces/";
const SPACE_DETAIL_PATH: ApiPath = "/api/v1/admin/spaces/{id}/";
const SPACE_DEACTIVATE_PATH: ApiPath = "/api/v1/admin/spaces/{id}/deactivate/";
const SPACE_BOOKINGS_PATH: ApiPath = "/api/v1/admin/spaces/{id}/bookings/";
const ACTION_PATHS = {
  approve: "/api/v1/admin/bookings/{id}/approve/",
  reject: "/api/v1/admin/bookings/{id}/reject/",
  cancel: "/api/v1/admin/bookings/{id}/cancel/",
  complete: "/api/v1/admin/bookings/{id}/complete/",
  "no-show": "/api/v1/admin/bookings/{id}/no-show/",
} satisfies Record<string, ApiPath>;
export type BookingAction = keyof typeof ACTION_PATHS;

function staffPath(path: ApiPath, replacements: Record<string, number>) {
  return Object.entries(replacements).reduce(
    (value, [key, replacement]) => value.replace("{" + key + "}", String(replacement)),
    path.replace("/api/v1", ""),
  );
}

export const bookingKeys = {
  all: (makerspaceId: number) => ["bookings", makerspaceId] as const,
  spaces: (makerspaceId: number) => [...bookingKeys.all(makerspaceId), "spaces"] as const,
  detail: (spaceId: number) => ["booking-space", spaceId] as const,
  bookings: (spaceId: number) => ["booking-space", spaceId, "bookings"] as const,
  availability: (spaceId: number) => ["booking-space", spaceId, "availability"] as const,
};

export function useBookableSpaces(makerspaceId: number, page = 1, query = "") {
  return useQuery({
    queryKey: [...bookingKeys.spaces(makerspaceId), page, query],
    queryFn: () => staffRequest<Paginated<BookableSpace>>(staffPath(SPACE_LIST_PATH, { makerspace_id: makerspaceId }) + "?" + (query || "page=" + page)),
  });
}

export function useBookableSpace(spaceId: number) {
  return useQuery({
    queryKey: bookingKeys.detail(spaceId),
    queryFn: () => staffRequest<BookableSpace>(staffPath(SPACE_DETAIL_PATH, { id: spaceId })),
  });
}

export function useSpaceBookings(spaceId: number, filters: BookingFilters, page = 1, ordering = "starts_at") {
  const timestamp = (value: string) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toISOString(); };
  const query = new URLSearchParams({ page: String(page), ordering });
  if (filters.status) query.set("status", filters.status);
  if (filters.booking_id) query.set("booking_id", String(filters.booking_id));
  if (filters.starts_at) query.set("starts_at", timestamp(filters.starts_at));
  if (filters.ends_at) query.set("ends_at", timestamp(filters.ends_at));
  return useQuery({
    queryKey: [...bookingKeys.bookings(spaceId), filters.status ?? "", filters.starts_at ?? "", filters.ends_at ?? "", filters.booking_id ?? "", page, ordering],
    queryFn: () => staffRequest<Paginated<Booking>>(staffPath(SPACE_BOOKINGS_PATH, { id: spaceId }) + "?" + query),
  });
}

function useSpaceInvalidation(makerspaceId: number, spaceId?: number) {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: bookingKeys.spaces(makerspaceId) }),
      queryClient.invalidateQueries({ queryKey: ["public-spaces"] }),
      queryClient.invalidateQueries({ queryKey: ["operations-report"] }),
      ...(spaceId === undefined ? [] : [
        queryClient.invalidateQueries({ queryKey: bookingKeys.detail(spaceId) }),
        queryClient.invalidateQueries({ queryKey: bookingKeys.bookings(spaceId) }),
        queryClient.invalidateQueries({ queryKey: bookingKeys.availability(spaceId) }),
        queryClient.invalidateQueries({ queryKey: ["public-space-availability"] }),
      ]),
    ]);
  };
}

export function useCreateBookableSpace(makerspaceId: number) {
  const invalidate = useSpaceInvalidation(makerspaceId);
  return useMutation({
    mutationFn: (payload: BookableSpacePayload) => staffRequest<BookableSpace>(
      staffPath(SPACE_LIST_PATH, { makerspace_id: makerspaceId }),
      { method: "POST", body: JSON.stringify(payload) },
    ),
    onSuccess: invalidate,
  });
}

export function useUpdateBookableSpace(makerspaceId: number, spaceId: number) {
  const invalidate = useSpaceInvalidation(makerspaceId, spaceId);
  return useMutation({
    mutationFn: (payload: Partial<BookableSpacePayload>) => staffRequest<BookableSpace>(
      staffPath(SPACE_DETAIL_PATH, { id: spaceId }),
      { method: "PATCH", body: JSON.stringify(payload) },
    ),
    onSuccess: invalidate,
  });
}

export function useDeactivateBookableSpace(makerspaceId: number, spaceId: number) {
  const invalidate = useSpaceInvalidation(makerspaceId, spaceId);
  return useMutation({
    mutationFn: () => staffRequest<BookableSpace>(
      staffPath(SPACE_DEACTIVATE_PATH, { id: spaceId }),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: invalidate,
  });
}

export function useBookingAction(makerspaceId: number, spaceId: number) {
  const invalidate = useSpaceInvalidation(makerspaceId, spaceId);
  return useMutation({
    mutationFn: ({ bookingId, action }: { bookingId: number; action: BookingAction }) => staffRequest<Booking>(
      staffPath(ACTION_PATHS[action], { id: bookingId }),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: invalidate,
  });
}
