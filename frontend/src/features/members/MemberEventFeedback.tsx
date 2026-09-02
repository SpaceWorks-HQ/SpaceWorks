import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { memberRequest } from "../../lib/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import { validateCustomAnswers, type CustomAnswers, type CustomFormQuestion } from "../forms/customFormTypes";

type Form = {
  survey: { title: string; questions: CustomFormQuestion[] };
  requires_auth: boolean;
  certificate: { id: number; status: string; revision: number } | null;
};

export function MemberEventFeedback({ makerspaceId, makerspaceSlug, registrationId, feedbackPath, certificate }: {
  makerspaceId: number;
  makerspaceSlug: string;
  registrationId: number;
  feedbackPath: string | null;
  certificate: { id: number; status: string; revision: number } | null;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const form = useQuery({
    queryKey: ["member", makerspaceSlug, "event-feedback", registrationId],
    queryFn: () => memberRequest<Form>(feedbackPath!),
    enabled: open && Boolean(feedbackPath),
  });
  const submit = useMutation({
    mutationFn: () => memberRequest(feedbackPath!, {
      method: "POST", body: JSON.stringify({ answers, ...(form.data?.requires_auth ? { email } : {}) }),
    }),
    onSuccess: async () => {
      setAnswers({});
      setEmail("");
      setErrors({});
      await client.invalidateQueries({ queryKey: ["member"] });
      await form.refetch();
    },
  });
  const download = useMutation({
    mutationFn: (certificateId: number) => memberRequest<{ url: string }>(`/member/makerspaces/${makerspaceId}/event-certificates/${certificateId}/download/`),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] });
      window.location.assign(result.url);
    },
  });

  return <div className="mt-2 grid gap-2">
    <div className="flex flex-wrap gap-2">
      {feedbackPath ? <button className="desk-button-ghost" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Close feedback" : "Leave feedback"}</button> : null}
      {certificate?.status === "active" ? <button className="desk-button-ghost" type="button" disabled={download.isPending} onClick={() => download.mutate(certificate.id)}>Download certificate</button> : null}
      {certificate?.status === "pending" ? <button className="desk-button-ghost" type="button" disabled={download.isPending} onClick={() => download.mutate(certificate.id)}>Prepare certificate</button> : null}
      {certificate?.status === "failed" ? <button className="desk-button-ghost" type="button" disabled={download.isPending} onClick={() => download.mutate(certificate.id)}>Retry certificate</button> : null}
      {certificate?.status === "revoked" ? <span className="text-xs text-danger">Certificate revoked.</span> : null}
    </div>
    {open && form.isLoading ? <p className="text-sm text-muted">Loading feedback form…</p> : null}
    {open && form.data ? <form className="mt-2 grid gap-4 rounded-lg border border-line p-3" onSubmit={(event) => { event.preventDefault(); const next = validateCustomAnswers(form.data!.survey.questions, answers); setErrors(next); if (!Object.keys(next).length) submit.mutate(); }}>
      <h3 className="title-section">{form.data.survey.title}</h3>
      <CustomFormFields schema={form.data.survey.questions} answers={answers} onChange={setAnswers} errors={errors} yesNoAsCheckbox />
      {form.data.requires_auth ? <label className="grid gap-1"><span className="eyebrow">Registration email</span><input className="desk-input" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label> : null}
      <button className="desk-button-primary" type="submit" disabled={submit.isPending}>{submit.isPending ? "Submitting…" : "Submit feedback"}</button>
      {submit.isSuccess ? <p className="text-sm text-success-ink">Feedback recorded.</p> : null}
    </form> : null}
    {form.error || submit.error || download.error ? <p className="text-sm text-danger" role="alert">{(form.error || submit.error || download.error)?.message}</p> : null}
  </div>;
}
