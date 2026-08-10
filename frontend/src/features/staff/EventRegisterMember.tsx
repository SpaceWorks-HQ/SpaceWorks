import { useState } from "react";

import { useEventEligibleMembers, useRegisterMemberForEvent } from "./eventsApi";

/**
 * Register a member for an event from the roster — the desk counterpart to public
 * self-registration.
 *
 * Only members of this makerspace appear, and only ones not already registered: a
 * picker entry whose every use returns "already registered" is an error the interface
 * should not have offered.
 *
 * The phone field appears only after the server asks for one. A registration needs a
 * contact number and the member's account may carry none, so rather than demanding it
 * every time, the form asks exactly when it turns out to be missing.
 */
export function EventRegisterMember({
  makerspaceId,
  eventId,
  disabled,
}: {
  makerspaceId: number;
  eventId: number;
  disabled: boolean;
}) {
  const [memberId, setMemberId] = useState("");
  const [phone, setPhone] = useState("");
  const [needsPhone, setNeedsPhone] = useState(false);
  const members = useEventEligibleMembers(eventId, !disabled);
  const register = useRegisterMemberForEvent(makerspaceId, eventId);

  if (disabled) return null;

  const submit = () => {
    register.mutate(
      { member_id: Number(memberId), ...(phone.trim() ? { phone: phone.trim() } : {}) },
      {
        onSuccess: () => {
          setMemberId("");
          setPhone("");
          setNeedsPhone(false);
        },
        onError: (error) => {
          setNeedsPhone(/phone/i.test(error instanceof Error ? error.message : ""));
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
          onChange={(event) => setMemberId(event.target.value)}
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
