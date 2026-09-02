import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staffRequest } from "../../lib/api";
import type { CustomAnswers, CustomFormQuestion } from "../forms/customFormTypes";
import { eventKeys, staffPath, type Paginated } from "./eventsApiTypes";
import { organizedEventKeys } from "./organizedEventsApi";

export type CertificateSummary = {
  id: number;
  status: "pending" | "rendering" | "active" | "failed" | "revoked";
  revision: number;
  issued_at: string;
  rendered_at: string | null;
  revoked_at: string | null;
};

export type FeedbackSurvey = {
  id: number;
  title: string;
  thank_you_text: string;
  questions: CustomFormQuestion[];
  is_open: boolean;
  certificate_enabled: boolean;
  answered_question_ids: string[];
  opened_at: string | null;
  closed_at: string | null;
  response_count?: number;
};

export type FeedbackResponse = {
  id: number;
  answers: { version: 1; answers: Array<CustomFormQuestion & { value: unknown }> };
  created_at: string;
  identity: { registration_id: number; name: string; email: string } | null;
  certificate: CertificateSummary | null;
};

export const feedbackKeys = {
  survey: (eventId: number) => ["event", eventId, "feedback-survey"] as const,
  responses: (eventId: number) => ["event", eventId, "feedback-responses"] as const,
};

function path(template: string, id: number) {
  return staffPath(template, { id });
}

export function useEventFeedbackSurvey(eventId: number) {
  return useQuery({
    queryKey: feedbackKeys.survey(eventId),
    queryFn: () => staffRequest<{ survey: FeedbackSurvey | null }>(path("/admin/events/{id}/feedback-survey/", eventId)),
  });
}

function useInvalidateFeedback(eventId: number, makerspaceId: number) {
  const client = useQueryClient();
  return async () => Promise.all([
    client.invalidateQueries({ queryKey: feedbackKeys.survey(eventId) }),
    client.invalidateQueries({ queryKey: feedbackKeys.responses(eventId) }),
    client.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
    client.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    client.invalidateQueries({ queryKey: organizedEventKeys.all }),
  ]);
}

export function useConfigureFeedbackSurvey(eventId: number, makerspaceId: number) {
  const invalidate = useInvalidateFeedback(eventId, makerspaceId);
  return useMutation({
    mutationFn: (payload: Pick<FeedbackSurvey, "title" | "thank_you_text" | "questions" | "certificate_enabled">) =>
      staffRequest<FeedbackSurvey>(path("/admin/events/{id}/feedback-survey/", eventId), {
        method: "PUT", body: JSON.stringify(payload),
      }),
    onSuccess: invalidate,
  });
}

function useSurveyAction(eventId: number, makerspaceId: number, action: "open" | "close") {
  const invalidate = useInvalidateFeedback(eventId, makerspaceId);
  return useMutation({
    mutationFn: () => staffRequest<FeedbackSurvey>(path(`/admin/events/{id}/feedback-survey/${action}/`, eventId), {
      method: "POST", body: JSON.stringify({}),
    }),
    onSuccess: invalidate,
  });
}

export const useOpenFeedbackSurvey = (eventId: number, makerspaceId: number) => useSurveyAction(eventId, makerspaceId, "open");
export const useCloseFeedbackSurvey = (eventId: number, makerspaceId: number) => useSurveyAction(eventId, makerspaceId, "close");

export function useEventFeedbackResponses(eventId: number, page: number, enabled: boolean) {
  return useQuery({
    queryKey: [...feedbackKeys.responses(eventId), page],
    queryFn: () => staffRequest<Paginated<FeedbackResponse>>(`${path("/admin/events/{id}/feedback-responses/", eventId)}?page=${page}`),
    enabled,
  });
}

export function useCorrectAttendance(makerspaceId: number, eventId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (registrationId: number) => staffRequest<{ status: string; revoked_certificates: number }>(
      path("/admin/event-registrations/{id}/correct-attendance/", registrationId),
      { method: "POST", body: JSON.stringify({}) },
    ),
    onSuccess: async () => Promise.all([
      client.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
      client.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
      client.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
      client.invalidateQueries({ queryKey: organizedEventKeys.all }),
      client.invalidateQueries({ queryKey: feedbackKeys.responses(eventId) }),
    ]),
  });
}

export function useCertificateAction(eventId: number, makerspaceId: number, action: "revoke" | "reissue") {
  const invalidate = useInvalidateFeedback(eventId, makerspaceId);
  return useMutation({
    mutationFn: (certificateId: number) => staffRequest<CertificateSummary>(
      path(`/admin/event-certificates/{id}/${action}/`, certificateId),
      { method: "POST", body: JSON.stringify(action === "revoke" ? { reason: "staff_revoked" } : {}) },
    ),
    onSuccess: invalidate,
  });
}

export async function certificateDownload(certificateId: number) {
  return staffRequest<{ url: string }>(path("/admin/event-certificates/{id}/download/", certificateId));
}

export function useCertificateDownload(eventId: number, makerspaceId: number) {
  const invalidate = useInvalidateFeedback(eventId, makerspaceId);
  return useMutation({
    mutationFn: certificateDownload,
    onSuccess: invalidate,
  });
}

export type FeedbackSubmission = { answers: CustomAnswers; email?: string };
