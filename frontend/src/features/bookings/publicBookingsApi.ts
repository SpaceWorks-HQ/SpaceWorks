import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import type { CustomAnswers, CustomFormSchema } from "../forms/customFormTypes";

export type PublicBookableSpace = {
  public_token: string;
  name: string;
  kind: "dev_room" | "bench" | "meeting" | "other";
  description: string;
  capacity: number;
  location: string;
  image_url: string;
  approval_mode: "instant" | "approve";
  custom_form: CustomFormSchema;
  show_public_availability: boolean;
  show_public_booker_names: boolean;
};

export type PublicAvailability = {
  public_token: string;
  starts_at: string;
  ends_at: string;
  availability: { starts_at: string; ends_at: string; booker_name: string | null }[] | null;
};

export type PublicBookingInput = {
  starts_at: string;
  ends_at: string;
  custom_answers?: CustomAnswers | null;
  website?: string;
};

export type PublicBookingResult = { status: "pending" | "confirmed" };

const SPACES_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/spaces/";
const AVAILABILITY_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/spaces/{public_token}/availability/";
const BOOK_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/spaces/{public_token}/book/";

function pathFor(path: ApiPath, slug: string, token?: string) {
  return path.replace("/api/v1", "")
    .replace("{makerspace_slug}", encodeURIComponent(slug))
    .replace("{public_token}", encodeURIComponent(token ?? ""));
}

export const publicBookingKeys = {
  all: (slug: string) => ["public-spaces", slug] as const,
  availabilityPrefix: (slug: string, token: string) => ["public-space-availability", slug, token] as const,
  availability: (slug: string, token: string, startsAt: string, endsAt: string) =>
    [...publicBookingKeys.availabilityPrefix(slug, token), startsAt, endsAt] as const,
};

export function usePublicSpaces(slug: string) {
  return useQuery({
    queryKey: publicBookingKeys.all(slug),
    queryFn: () => tenantPublicRequest<PublicBookableSpace[]>(slug, pathFor(SPACES_PATH, slug)),
    enabled: Boolean(slug),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
}

export function usePublicAvailability(slug: string, token: string, startsAt: string, endsAt: string, enabled = true) {
  return useQuery({
    queryKey: publicBookingKeys.availability(slug, token, startsAt, endsAt),
    queryFn: () => {
      const query = new URLSearchParams({ starts_at: startsAt, ends_at: endsAt });
      return tenantPublicRequest<PublicAvailability>(slug, pathFor(AVAILABILITY_PATH, slug, token) + "?" + query);
    },
    enabled: enabled && Boolean(slug && token && startsAt && endsAt),
    retry: (count, error) => !(error instanceof StructuredApiError && error.status < 500) && count < 2,
  });
}

export function useSubmitPublicBooking(slug: string, token: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PublicBookingInput) => tenantPublicRequest<PublicBookingResult>(
      slug,
      pathFor(BOOK_PATH, slug, token),
      { method: "POST", body: JSON.stringify(payload) },
    ),
    onSuccess: async (result) => {
      if (result.status === "confirmed") {
        await queryClient.invalidateQueries({ queryKey: publicBookingKeys.availabilityPrefix(slug, token) });
      }
    },
  });
}
