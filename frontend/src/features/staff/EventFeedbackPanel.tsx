import { useEffect, useState } from "react";

import { Skeleton, StatusBadge } from "../../components/ui";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { CustomFormQuestion } from "../forms/customFormTypes";
import {
  useCloseFeedbackSurvey,
  useConfigureFeedbackSurvey,
  useEventFeedbackSurvey,
  useOpenFeedbackSurvey,
} from "./eventFeedbackApi";
import { EventFeedbackResponses } from "./EventFeedbackResponses";
import { eventErrorText } from "./eventUi";

const FEEDBACK_TYPES = [
  "short_text", "paragraph", "number", "single_choice", "multi_choice", "dropdown", "yes_no",
] as const;

export function EventFeedbackPanel({ eventId, makerspaceId }: { eventId: number; makerspaceId: number }) {
  const surveyQuery = useEventFeedbackSurvey(eventId);
  const survey = surveyQuery.data?.survey;
  const [title, setTitle] = useState("");
  const [thankYou, setThankYou] = useState("");
  const [questions, setQuestions] = useState<CustomFormQuestion[]>([]);
  const [certificateEnabled, setCertificateEnabled] = useState(false);
  const configure = useConfigureFeedbackSurvey(eventId, makerspaceId);
  const open = useOpenFeedbackSurvey(eventId, makerspaceId);
  const close = useCloseFeedbackSurvey(eventId, makerspaceId);

  useEffect(() => {
    if (!survey) return;
    setTitle(survey.title);
    setThankYou(survey.thank_you_text);
    setQuestions(survey.questions);
    setCertificateEnabled(survey.certificate_enabled);
  }, [survey?.id, survey?.is_open, survey?.answered_question_ids.join("|")]);

  const error = configure.error || open.error || close.error;
  const pending = configure.isPending || open.isPending || close.isPending;

  return <section className="border-t border-line pt-5" aria-labelledby="feedback-title">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h3 id="feedback-title" className="title-section">Post-event feedback</h3>
        <p className="text-sm text-muted">Answered questions stay immutable; unopened questions remain editable.</p>
      </div>
      {survey ? <StatusBadge status={survey.is_open ? "open" : "closed"} /> : null}
    </div>
    {surveyQuery.isLoading ? <Skeleton className="mt-3 h-32 w-full" /> : null}
    {surveyQuery.error ? <p className="mt-3 text-sm text-danger">{eventErrorText(surveyQuery.error)}</p> : null}
    {!surveyQuery.isLoading ? <form className="mt-4 grid gap-3" onSubmit={(event) => {
      event.preventDefault();
      configure.mutate({ title, thank_you_text: thankYou, questions, certificate_enabled: certificateEnabled });
    }}>
      <label className="grid gap-1"><span className="eyebrow">Survey title</span><input className="desk-input" required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      <label className="grid gap-1"><span className="eyebrow">Thank-you message</span><textarea className="desk-input min-h-20" maxLength={2000} value={thankYou} onChange={(event) => setThankYou(event.target.value)} /></label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={certificateEnabled} onChange={(event) => setCertificateEnabled(event.target.checked)} />Require an attended member and issue an attendance certificate</label>
      <CustomFormBuilder value={questions} onChange={(value) => setQuestions(value ?? [])} allowedTypes={FEEDBACK_TYPES} lockedQuestionIds={survey?.answered_question_ids} legend="Feedback questions" emptyMessage="Add at least one question before opening the survey." />
      <div className="flex flex-wrap gap-2">
        <button className="desk-button-primary" type="submit" disabled={pending}>Save survey</button>
        {survey && !survey.is_open ? <button className="desk-button-success" type="button" disabled={pending} onClick={() => open.mutate()}>Open responses</button> : null}
        {survey?.is_open ? <button className="desk-button-danger" type="button" disabled={pending} onClick={() => close.mutate()}>Close responses</button> : null}
      </div>
    </form> : null}
    {error ? <p className="mt-2 text-sm text-danger" role="alert">{eventErrorText(error)}</p> : null}
    {survey ? <EventFeedbackResponses eventId={eventId} makerspaceId={makerspaceId} responseCount={survey.response_count ?? 0} /> : null}
  </section>;
}
