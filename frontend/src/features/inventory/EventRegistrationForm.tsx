import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";

type RegistrationResult = { status: "pending_approval" | "registered" | "waitlisted" };

const REGISTER_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/events/{public_token}/register/";

function registerPath(slug: string, token: string) {
  return REGISTER_PATH.replace("/api/v1", "")
    .replace("{makerspace_slug}", encodeURIComponent(slug))
    .replace("{public_token}", encodeURIComponent(token));
}

function failureMessage(error: StructuredApiError | null) {
  if (!error) return "The registration could not be submitted.";
  if (error.status === 401) return "Sign in to register for this event.";
  if (error.status === 403 && error.code === "membership_required") return "Join this makerspace before registering.";
  if (error.status === 403 && error.code === "waiver_acceptance_required") return "Accept the current waiver before registering.";
  if (error.status === 403 && error.code === "presence_required") return "Start a presence session before registering.";
  if (error.status === 429) return "Too many registration attempts. Please wait and try again.";
  if (error.status === 409 && error.code === "registration_closed") return "Registration for this event is closed.";
  if (error.status === 409 && error.code === "registration_rejected") return "Your application was not approved and cannot be resubmitted.";
  return error.detail ?? error.message;
}

export function EventRegistrationForm({ makerspaceSlug, publicToken, waitlist, approvalRequired }: {
  makerspaceSlug: string; publicToken: string; waitlist: boolean; approvalRequired: boolean;
}) {
  const queryClient = useQueryClient();
  const [website, setWebsite] = useState("");
  const successRef = useRef<HTMLDivElement>(null);
  const registration = useMutation({
    mutationFn: async () => {
      const rawTransportBody = { website };
      return tenantPublicRequest<RegistrationResult>(makerspaceSlug, registerPath(makerspaceSlug, publicToken), {
        method: "POST", body: JSON.stringify(rawTransportBody),
      });
    },
    onSuccess: async () => { await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["public-events", makerspaceSlug] }),
      queryClient.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] }),
    ]); },
  });
  useEffect(() => { if (registration.data) successRef.current?.focus(); }, [registration.data]);

  if (registration.data) {
    return <div ref={successRef} className="rounded-lg border border-line bg-surface p-4 outline-none" role="status" tabIndex={-1}>
      <h3 className="title-section">{registration.data.status === "pending_approval" ? "Application awaiting approval" : registration.data.status === "waitlisted" ? "You’re on the waitlist" : "Registration received"}</h3>
      <p className="mt-1 text-sm text-muted">{registration.data.status === "pending_approval" ? "You will only be charged if a place is confirmed." : registration.data.status === "waitlisted" ? "The makerspace has recorded your waitlist request." : "The makerspace has recorded your registration."}</p>
    </div>;
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!registration.isPending) registration.mutate();
  };
  const apiError = registration.error instanceof StructuredApiError ? registration.error : null;

  return <form className="grid gap-3 rounded-lg border border-line bg-bg p-4" onSubmit={submit} noValidate>
    <h3 className="title-section">{approvalRequired ? "Apply" : waitlist ? "Join the waitlist" : "Register"}</h3>
    <label className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">Website
      <input name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
    </label>
    {registration.error ? <p className="text-sm text-danger" role="alert">{failureMessage(apiError)}</p> : null}
    <button className="desk-button-primary" type="submit" disabled={registration.isPending}>
      {registration.isPending ? "Submitting..." : approvalRequired ? "Apply" : waitlist ? "Join waitlist" : "Register"}
    </button>
  </form>;
}
