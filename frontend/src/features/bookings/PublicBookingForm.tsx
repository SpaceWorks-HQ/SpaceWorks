import { useEffect, useRef, useState, type FormEvent } from "react";

import { Field } from "../../components/ui";
import { StructuredApiError } from "../../lib/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import {
  customAnswerErrors,
  validateCustomAnswers,
  type CustomAnswers,
} from "../forms/customFormTypes";
import { AvailabilityCalendar } from "./AvailabilityCalendar";
import { useSubmitPublicBooking, type PublicBookableSpace } from "./publicBookingsApi";

type StandardErrors = Partial<Record<"starts_at" | "ends_at", string>>;

function apiFieldError(error: StructuredApiError | null, field: keyof StandardErrors) {
  const value = error?.body[field];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === "string").join(" ");
  return "";
}

function failureMessage(error: StructuredApiError | null) {
  if (!error) return "The booking could not be submitted. Please try again.";
  if (error.status === 409) return "That time now overlaps a confirmed booking. Choose another slot and try again.";
  if (error.status === 429) return "Too many booking attempts were made. Please wait before trying again.";
  if (error.status === 401) return "Sign in to submit a booking.";
  if (error.status === 403) {
    if (error.code === "membership_required") return "Join this makerspace before booking.";
    if (error.code === "waiver_acceptance_required") return "Accept the current waiver before booking.";
    if (error.code === "presence_required") return "Start a presence session before booking.";
  }
  if (error.status === 400) return error.detail ?? "Review the highlighted fields and try again.";
  return error.detail ?? "The booking service is unavailable. Please try again.";
}

export function PublicBookingForm({ makerspaceSlug, space }: {
  makerspaceSlug: string;
  space: PublicBookableSpace;
}) {
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [website, setWebsite] = useState("");
  const [standardErrors, setStandardErrors] = useState<StandardErrors>({});
  const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
  const successRef = useRef<HTMLDivElement>(null);
  const booking = useSubmitPublicBooking(makerspaceSlug, space.public_token);
  const apiError = booking.error instanceof StructuredApiError ? booking.error : null;
  const serverAnswerErrors = customAnswerErrors(apiError?.body.custom_answers);

  useEffect(() => {
    if (booking.data) successRef.current?.focus();
  }, [booking.data]);

  if (booking.data) {
    const pending = booking.data.status === "pending";
    return (
      <div ref={successRef} className={`rounded-lg border ${pending ? "border-warn bg-warn/15" : "border-success bg-success/15"} p-4 outline-none`} role="status" tabIndex={-1}>
        <h3 className="title-section">{pending ? "Booking request received" : "Space booked"}</h3>
        <p className="mt-1 text-sm text-muted">
          {pending ? "Staff must approve this request before the slot is confirmed." : "Your selected slot is confirmed and booked."}
        </p>
      </div>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (booking.isPending) return;
    const nextStandard: StandardErrors = {};
    if (!startsAt) nextStandard.starts_at = "Choose a start time.";
    if (!endsAt) nextStandard.ends_at = "Choose an end time.";
    if (startsAt && endsAt && new Date(endsAt) <= new Date(startsAt)) nextStandard.ends_at = "End time must be after start time.";
    if (endsAt && new Date(endsAt) <= new Date()) nextStandard.ends_at = "End time must be in the future.";
    const nextAnswers = validateCustomAnswers(space.custom_form, answers);
    setStandardErrors(nextStandard);
    setAnswerErrors(nextAnswers);
    if (Object.keys(nextStandard).length || Object.keys(nextAnswers).length) return;

    booking.mutate({
      starts_at: new Date(startsAt).toISOString(),
      ends_at: new Date(endsAt).toISOString(),
      custom_answers: Object.keys(answers).length ? answers : null,
      website,
    });
  };
  const errorFor = (field: keyof StandardErrors) => standardErrors[field] || apiFieldError(apiError, field);

  return (
    <div className="grid gap-4">
      <AvailabilityCalendar makerspaceSlug={makerspaceSlug} publicToken={space.public_token} />
      <form className="grid gap-4 rounded-lg border border-secondary bg-bg p-4" onSubmit={submit} noValidate>
        <div>
          <h3 className="title-section">Request this space</h3>
          <p className="eyebrow mt-1">Times are shown in your device timezone.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Starts" error={errorFor("starts_at")}><input className="desk-input" type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} required /></Field>
          <Field label="Ends" error={errorFor("ends_at")}><input className="desk-input" type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} required /></Field>
        </div>
        <CustomFormFields schema={space.custom_form} answers={answers} onChange={setAnswers} errors={{ ...answerErrors, ...serverAnswerErrors }} disabled={booking.isPending} />
        <label className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">Website
          <input name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(event) => setWebsite(event.target.value)} />
        </label>
        {booking.error ? <p className="text-sm text-danger" role="alert">{failureMessage(apiError)}</p> : null}
        <button className="desk-button-secondary" type="submit" disabled={booking.isPending}>
          {booking.isPending ? "Submitting..." : space.approval_mode === "approve" ? "Submit booking request" : "Book this slot"}
        </button>
      </form>
    </div>
  );
}
