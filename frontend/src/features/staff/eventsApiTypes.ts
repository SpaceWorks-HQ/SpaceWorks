import type { ApiPath } from "../../generated/api";
import type { CustomFormSchema } from "../forms/customFormTypes";
import type { PaymentSummary } from "./PaymentReconcileActions";

export type EventStatus = "draft" | "published" | "cancelled" | "completed";
export type EventRegistrationStatus =
  | "pending_approval"
  | "registered"
  | "waitlisted"
  | "rejected"
  | "cancelled"
  | "attended";
export type EventRegistrationCounts = Record<EventRegistrationStatus, number>;

export type StaffEvent = {
  id: number;
  makerspace_id: number;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  timezone_name: string;
  location: string;
  capacity: number;
  payment_amount: string;
  registration_requires_approval: boolean;
  registration_cutoff_at: string | null;
  registration_cutoff_lead_minutes: number | null;
  effective_registration_cutoff_at: string | null;
  registration_open: boolean;
  is_public: boolean;
  image_url: string | null;
  status: EventStatus;
  custom_form: CustomFormSchema | null;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
  registration_counts: EventRegistrationCounts;
  series_summary: {
    id: number; public_token: string; title: string; timezone: string;
  } | null;
  series_revision: number | null;
  series_override_fields: string[];
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
  timezone_name: string;
  location: string;
  capacity: number;
  payment_amount: string;
  registration_requires_approval: boolean;
  registration_cutoff_at: string | null;
  registration_cutoff_lead_minutes: number | null;
  is_public: boolean;
  custom_form: CustomFormSchema;
};

export type EventPatch = Partial<EventPayload> & { inherit_fields?: string[] };
export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export const EVENT_LIST_PATH: ApiPath = "/api/v1/admin/makerspaces/{makerspace_id}/events/";
export const EVENT_DETAIL_PATH: ApiPath = "/api/v1/admin/events/{id}/";
export const EVENT_PUBLISH_PATH: ApiPath = "/api/v1/admin/events/{id}/publish/";
export const EVENT_CANCEL_PATH: ApiPath = "/api/v1/admin/events/{id}/cancel/";
export const EVENT_COMPLETE_PATH: ApiPath = "/api/v1/admin/events/{id}/complete/";
export const EVENT_REGISTRATIONS_PATH: ApiPath = "/api/v1/admin/events/{id}/registrations/";
export const MARK_ATTENDED_PATH: ApiPath = "/api/v1/admin/event-registrations/{id}/mark-attended/";
export const CHECK_IN_RESOLVE_PATH: ApiPath = "/api/v1/admin/events/{id}/check-in/resolve/";
export const ELIGIBLE_MEMBERS_PATH: ApiPath = "/api/v1/admin/events/{id}/eligible-members/";

export function staffPath(path: string, replacements: Record<string, number>) {
  return Object.entries(replacements).reduce(
    (value, [key, replacement]) => value.replace(`{${key}}`, String(replacement)),
    path.replace("/api/v1", ""),
  );
}

export const eventKeys = {
  all: (makerspaceId: number) => ["events", makerspaceId] as const,
  list: (makerspaceId: number) => ["events", makerspaceId, "list"] as const,
  detail: (eventId: number) => ["event", eventId] as const,
  registrations: (eventId: number) => ["event", eventId, "registrations"] as const,
  badgeTemplate: (eventId: number) => ["event", eventId, "badge-template"] as const,
};

export function eligibleMemberKey(eventId: number) {
  return ["event", eventId, "eligible-members"] as const;
}
