import { useState } from "react";
import { CustomFormFields } from "../forms/CustomFormFields";
import { customAnswerErrors, validateCustomAnswers, type CustomAnswers } from "../forms/customFormTypes";
import { StructuredApiError } from "../../lib/api";
import type { PublicAdmission } from "./membershipAdmissionApi";

export function AdmissionJoin({ settings, signedIn, pending, error, onJoin, onSignIn }: {
  settings: PublicAdmission;
  signedIn: boolean;
  pending: boolean;
  error?: unknown;
  onJoin: (answers: CustomAnswers) => void;
  onSignIn: () => void;
}) {
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const mode = settings.join_mode;
  const blocked = mode === "closed" || mode === "invite_only";
  const paid = Number(settings.default_plan?.amount ?? 0) > 0 || Number(settings.joining_fee) > 0;
  const payFirst = paid && settings.payment_timing === "before_activation";
  const label = mode === "open" ? payFirst ? "Apply to join" : "Join instantly" : "Request to join";
  return <section className="desk-panel p-5">
    <h2 className="title-panel">{mode === "closed" ? "Membership applications are closed" : mode === "invite_only" ? "Invite-only makerspace" : "Join this makerspace"}</h2>
    <p className="mt-1 text-sm text-muted">{mode === "closed" ? "This makerspace is not accepting new members." : mode === "invite_only" ? "Ask a space manager for an invitation." : mode === "vouch" ? `You need ${settings.vouches_required} member vouch(es) before your application can proceed.` : mode === "approval" ? "Staff will review your application." : payFirst ? "Your membership activates after the admission charge is settled." : "You will become a member immediately."}</p>
    {!blocked && settings.default_plan ? <p className="mt-2 text-sm text-ink">Plan: {settings.default_plan.name} · {settings.default_plan.amount} {settings.default_plan.currency.toUpperCase()}</p> : null}
    {!blocked && Number(settings.joining_fee) > 0 ? <p className="mt-2 text-sm text-ink">Joining fee: {settings.joining_fee} {(settings.joining_fee_currency ?? settings.default_plan?.currency ?? "").toUpperCase()}</p> : null}
    {!blocked && paid ? <p className="mt-2 text-sm text-muted">{payFirst ? "Payment is required before activation. You can pay online when available, or at the space." : "Charges are recorded when your membership activates."}</p> : null}
    {!blocked && signedIn ? <form className="mt-4 grid gap-4" onSubmit={(event) => {
      event.preventDefault();
      const next = validateCustomAnswers(settings.application_schema, answers);
      setErrors(next);
      if (!Object.keys(next).length) onJoin(answers);
    }}>
      <CustomFormFields schema={settings.application_schema} answers={answers} onChange={setAnswers} disabled={pending} errors={{ ...errors, ...customAnswerErrors(error instanceof StructuredApiError ? error.body.application_answers : null) }} />
      <button className="desk-button-secondary w-fit" disabled={pending} type="submit">{pending ? "Sending…" : label}</button>
    </form> : !blocked ? <button className="desk-button-secondary mt-4" onClick={onSignIn} type="button">Sign in to join</button> : null}
    {error ? <p role="alert" className="mt-3 text-sm text-danger">{error instanceof Error ? error.message : "Unable to submit your application."}</p> : null}
  </section>;
}
