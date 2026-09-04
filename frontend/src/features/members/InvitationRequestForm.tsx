import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Field } from "../../components/ui";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";

type Ack = { detail: string };

const EMPTY = { name: "", email: "", phone: "", message: "", website: "" };

/**
 * Public "ask to be invited" form (`POST /public/<slug>/invitation-requests`). `website` is
 * the honeypot the backend checks first: a filled value gets the same 202 acknowledgement
 * as a real submission and stores nothing, so the field must be present but never seen by a
 * person -- it is rendered display:none, out of the tab order and out of autofill.
 */
export function InvitationRequestForm({ slug }: { slug: string }) {
  const [form, setForm] = useState(EMPTY);
  const submit = useMutation({
    mutationFn: () =>
      tenantPublicRequest<Ack>(slug, `/public/${slug}/invitation-requests`, {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim(),
          phone: form.phone.trim(),
          message: form.message.trim(),
          website: form.website,
        }),
      }),
    onSuccess: () => setForm(EMPTY),
  });
  const set = (key: keyof typeof EMPTY, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const canSubmit = form.name.trim().length > 0 && form.email.trim().length > 0 && !submit.isPending;

  return (
    <section className="desk-panel p-5" aria-labelledby="invitation-request-heading">
      <h2 id="invitation-request-heading" className="title-panel">Ask for an invitation</h2>
      <p className="mt-1 text-sm text-muted">Leave your details and the makerspace will get back to you.</p>
      {submit.isSuccess ? (
        <p className="mt-4 rounded-md border border-success/40 bg-success/10 px-3 py-2 text-sm text-ink" role="status">
          {submit.data.detail}
        </p>
      ) : (
        <form
          className="mt-4 grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmit) submit.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">
              <input className="desk-input" required maxLength={200} autoComplete="name" value={form.name} onChange={(event) => set("name", event.target.value)} />
            </Field>
            <Field label="Email">
              <input className="desk-input" required type="email" maxLength={254} autoComplete="email" value={form.email} onChange={(event) => set("email", event.target.value)} />
            </Field>
            <Field label="Phone (optional)" className="sm:col-span-2">
              <input className="desk-input" type="tel" maxLength={32} autoComplete="tel" value={form.phone} onChange={(event) => set("phone", event.target.value)} />
            </Field>
          </div>
          <Field label="Message (optional)">
            <textarea className="desk-input min-h-24" maxLength={1000} value={form.message} onChange={(event) => set("message", event.target.value)} />
          </Field>
          <div className="hidden" aria-hidden="true">
            <label>
              Website
              <input name="website" tabIndex={-1} autoComplete="off" value={form.website} onChange={(event) => set("website", event.target.value)} />
            </label>
          </div>
          <button className="desk-button-secondary w-fit" type="submit" disabled={!canSubmit}>
            {submit.isPending ? "Sending…" : "Send request"}
          </button>
          {submit.error ? (
            <p className="text-sm text-danger" role="alert">{invitationErrorText(submit.error)}</p>
          ) : null}
        </form>
      )}
    </section>
  );
}

function invitationErrorText(error: unknown) {
  if (error instanceof StructuredApiError) {
    if (error.status === 429) return "Too many requests from this connection. Please try again later.";
    if (error.status === 404) return "This makerspace is not taking invitation requests right now.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Could not send your request.";
}
