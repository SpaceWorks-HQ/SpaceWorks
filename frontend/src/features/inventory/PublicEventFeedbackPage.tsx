import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { SiteFooter } from "../../components/SiteFooter";
import { Card, Skeleton } from "../../components/ui";
import { getAccessToken, refreshAccessToken, StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { CustomFormFields } from "../forms/CustomFormFields";
import { customAnswerErrors, validateCustomAnswers, type CustomAnswers, type CustomFormQuestion } from "../forms/customFormTypes";

type FeedbackForm = {
  event: { title: string; starts_at: string; ends_at: string };
  survey: { title: string; thank_you_text: string; questions: CustomFormQuestion[] };
  mode: "anonymous" | "certificate";
  requires_auth: boolean;
  certificate: { id: number; status: string; revision: number } | null;
};

function feedbackPath(slug: string, token: string) {
  return `/public/${encodeURIComponent(slug)}/events/${encodeURIComponent(token)}/feedback/`;
}

export function PublicEventFeedbackPage() {
  const { slug, publicToken = "" } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const client = useQueryClient();
  const path = feedbackPath(makerspaceSlug, publicToken);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [restored, setRestored] = useState(Boolean(getAccessToken()));
  const form = useQuery({
    queryKey: ["public-event-feedback", makerspaceSlug, publicToken],
    queryFn: () => tenantPublicRequest<FeedbackForm>(makerspaceSlug, path),
  });
  useEffect(() => {
    if (form.data?.requires_auth && !restored) refreshAccessToken().then(setRestored);
  }, [form.data?.requires_auth, restored]);
  const submit = useMutation({
    mutationFn: () => tenantPublicRequest<{ thank_you_text: string; certificate: FeedbackForm["certificate"] }>(makerspaceSlug, path, {
      method: "POST", body: JSON.stringify({ answers, ...(form.data?.requires_auth ? { email } : {}) }),
    }),
    onSuccess: async () => {
      setAnswers({}); setEmail(""); setErrors({});
      await client.invalidateQueries({ queryKey: ["public-event-feedback", makerspaceSlug, publicToken] });
    },
  });
  const apiErrors = submit.error instanceof StructuredApiError ? submit.error.body.answers : undefined;

  if (form.isLoading) return <main className="desk-shell grid min-h-screen place-items-center px-5"><Skeleton className="h-64 w-full max-w-2xl" /></main>;
  if (form.error || !form.data) return <main className="desk-shell grid min-h-screen place-items-center px-5"><Card><h1 className="title-page">Feedback unavailable</h1><p className="mt-2 text-sm text-muted">This survey is closed, the event has not ended, or the link is invalid.</p><Link className="desk-button mt-4" to={tenantPath("events")}>Back to events</Link></Card></main>;
  if (submit.data) return <main className="desk-shell grid min-h-screen place-items-center px-5"><Card><h1 className="title-page">Thank you</h1><p className="mt-2 text-sm text-muted">{submit.data.thank_you_text || "Your response was recorded."}</p>{submit.data.certificate ? <p className="mt-3 text-sm text-ink">Your certificate is being prepared. Download it from Member activity.</p> : null}<Link className="desk-button mt-4" to={tenantPath("member")}>Open member area</Link></Card></main>;

  const data = form.data;
  return <main className="desk-shell flex min-h-screen flex-col"><section className="mx-auto w-full max-w-2xl flex-1 px-5 py-10">
    <p className="eyebrow">{data.event.title}</p><h1 className="title-page mt-2">{data.survey.title}</h1>
    <p className="mt-2 text-sm text-muted">{data.mode === "anonymous" ? "No account or response identifier is stored with this response." : "Certificates are available only to members recorded as attended."}</p>
    {data.requires_auth && !restored ? <Card className="mt-5"><p className="text-sm text-muted">Sign in through the member area before submitting certificate feedback.</p><Link className="desk-button-primary mt-3" to={tenantPath("member")}>Member sign in</Link></Card> : null}
    <form className="desk-panel mt-5 grid gap-5 p-5" onSubmit={(event) => { event.preventDefault(); const next = validateCustomAnswers(data.survey.questions, answers); setErrors(next); if (!Object.keys(next).length) submit.mutate(); }}>
      <CustomFormFields schema={data.survey.questions} answers={answers} onChange={setAnswers} errors={{ ...errors, ...customAnswerErrors(apiErrors) }} yesNoAsCheckbox />
      {data.requires_auth ? <label className="grid gap-1"><span className="eyebrow">Registration email</span><input className="desk-input" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label> : null}
      <button className="desk-button-primary" type="submit" disabled={submit.isPending || (data.requires_auth && !restored)}>{submit.isPending ? "Submitting..." : "Submit feedback"}</button>
      {submit.error ? <p className="text-sm text-danger" role="alert">{submit.error.message}</p> : null}
    </form>
  </section><SiteFooter /></main>;
}
