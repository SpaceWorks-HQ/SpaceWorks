import { useState } from "react";

import { CustomFormFields } from "../forms/CustomFormFields";
import {
  customAnswerErrors,
  validateCustomAnswers,
  type CustomAnswers,
} from "../forms/customFormTypes";
import { StructuredApiError } from "../../lib/api";
import { useEventEligibleMembers, useRegisterMemberForEvent, type StaffEvent } from "./eventsApi";

/**
 * Register a member for an event from the roster — the desk counterpart to public
 * self-registration.
 *
 * Only members of this makerspace appear, and only ones not already registered: a
 * picker entry whose every use returns "already registered" is an error the interface
 * should not have offered.
 *
 * The phone and email fields appear only after the server asks for one. A registration
 * needs both a contact number and an address, and a staff-created walk-in may carry
 * neither, so rather than demanding them every time, the form asks exactly when one
 * turns out to be missing. Without these the backend's fallbacks would be unreachable
 * from the console, which is the same as not having them: the members this program made
 * registrable are precisely the ones whose accounts are empty.
 */
export function EventRegisterMember({
  makerspaceId,
  eventId,
  customForm,
  disabled,
}: {
  makerspaceId: number;
  eventId: number;
  customForm: StaffEvent["custom_form"];
  disabled: boolean;
}) {
  const [memberId, setMemberId] = useState("");
  const [phone, setPhone] = useState("");
  const [needsPhone, setNeedsPhone] = useState(false);
  const [email, setEmail] = useState("");
  const [needsEmail, setNeedsEmail] = useState(false);
  // Without this the console could never register anyone for an event whose form has a
  // required question: the backend validates answers on this path exactly as it does for
  // public self-registration, so a form with no way to answer it is a permanent 400.
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
  const members = useEventEligibleMembers(eventId, !disabled);
  const register = useRegisterMemberForEvent(makerspaceId, eventId);

  if (disabled) return null;

  const serverAnswerErrors = customAnswerErrors(
    register.error instanceof StructuredApiError
      ? register.error.body.custom_answers
      : undefined,
  );
  const submit = () => {
    // Validated here as well as on the server, so a missing required answer is shown
    // beside the question rather than returned as a whole-form 400.
    const nextErrors = validateCustomAnswers(customForm ?? [], answers);
    setAnswerErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    register.mutate(
      {
        member_id: Number(memberId),
        ...(phone.trim() ? { phone: phone.trim() } : {}),
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(customForm?.length ? { custom_answers: answers } : {}),
      },
      {
        onSuccess: () => {
          setMemberId("");
          setPhone("");
          setNeedsPhone(false);
          setEmail("");
          setNeedsEmail(false);
          setAnswers({});
          setAnswerErrors({});
        },
        onError: (error) => {
          // Read the FIELD-KEYED body, never the message. `StructuredApiError` builds
          // its message from `Object.values(body)` alone, so a DRF field error arrives
          // as the bare string "This field cannot be blank." — it contains neither
          // "phone" nor "email", and matching on it never fires. That is why the phone
          // prompt this mirrors had never once appeared.
          //
          // A record missing both fields is refused on one of them at a time, so these
          // accumulate rather than replace each other — clearing the phone prompt when
          // the next attempt fails on email would hide the answer just given.
          if (!(error instanceof StructuredApiError)) return;
          if (error.body.phone) setNeedsPhone(true);
          if (error.body.email) setNeedsEmail(true);
        },
      },
    );
  };

  return (
    <div className="mt-3 rounded-lg border border-line bg-surface p-3">
      <label className="block text-sm font-semibold text-ink" htmlFor="event-register-member">
        Register a member
      </label>
      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
        <select
          id="event-register-member"
          className="desk-input w-full"
          value={memberId}
          disabled={members.isLoading}
          onChange={(event) => {
            setMemberId(event.target.value);
            // A fallback contact belongs to one specific person and must never carry
            // across to another.
            setPhone("");
            setNeedsPhone(false);
            setEmail("");
            setNeedsEmail(false);
          }}
        >
          <option value="">
            {members.isLoading ? "Loading members…" : "Select a member"}
          </option>
          {(members.data ?? []).map((row) => (
            <option key={row.member_id} value={row.member_id}>
              {row.display_name}
            </option>
          ))}
        </select>
        <button
          className="desk-button-primary shrink-0"
          type="button"
          disabled={!memberId || register.isPending}
          onClick={submit}
        >
          {register.isPending ? "Registering…" : "Register"}
        </button>
      </div>
      {customForm?.length ? (
        <div className="mt-3">
          <CustomFormFields
            schema={customForm}
            answers={answers}
            onChange={setAnswers}
            errors={{ ...answerErrors, ...serverAnswerErrors }}
            disabled={register.isPending}
          />
        </div>
      ) : null}
      {needsPhone ? (
        <div className="mt-2">
          <label className="block text-sm font-semibold text-ink" htmlFor="event-register-phone">
            Contact number
          </label>
          <input
            id="event-register-phone"
            className="desk-input mt-1 w-full"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
          <p className="mt-1 text-xs text-muted">
            This member&apos;s account has no number on file.
          </p>
        </div>
      ) : null}
      {needsEmail ? (
        <div className="mt-2">
          <label className="block text-sm font-semibold text-ink" htmlFor="event-register-email">
            Contact email
          </label>
          <input
            id="event-register-email"
            type="email"
            className="desk-input mt-1 w-full"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <p className="mt-1 text-xs text-muted">
            This member&apos;s account has no address on file.
          </p>
        </div>
      ) : null}
      {register.error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {register.error instanceof Error ? register.error.message : "Could not register."}
        </p>
      ) : null}
      {members.data && !members.data.length ? (
        <p className="mt-2 text-sm text-muted">Every member is already registered.</p>
      ) : null}
    </div>
  );
}
