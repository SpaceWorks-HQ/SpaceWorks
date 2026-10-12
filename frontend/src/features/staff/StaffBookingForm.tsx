import { useState, type FormEvent } from "react";

import { StructuredApiError } from "../../lib/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import { customAnswerErrors, validateCustomAnswers, type CustomAnswers } from "../forms/customFormTypes";
import type { BookableSpace } from "./bookingsApi";
import { useBookingEligibleMembers, useStaffCreateBooking } from "./staffBookingApi";

export function StaffBookingForm({ makerspaceId, space, recurringEnabled = false }: { makerspaceId: number; space: BookableSpace; recurringEnabled?: boolean }) {
  const [repeat, setRepeat] = useState(false);
  const [count, setCount] = useState(8);
  const [intervalWeeks, setIntervalWeeks] = useState(1);
  const [memberId, setMemberId] = useState("");
  const [page, setPage] = useState(1);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const members = useBookingEligibleMembers(space.id, page);
  const create = useStaffCreateBooking(makerspaceId, space.id);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextErrors = validateCustomAnswers(space.custom_form ?? [], answers);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    create.mutate({
      ...(repeat && recurringEnabled ? { count, interval_weeks: intervalWeeks } : {}),
      member_id: Number(memberId), starts_at: new Date(start).toISOString(),
      ends_at: new Date(end).toISOString(), note,
      ...(reason.trim() ? { certification_override_reason: reason.trim() } : {}),
      ...(space.custom_form?.length ? { custom_answers: answers } : {}),
    }, { onSuccess: () => { setMemberId(""); setAnswers({}); setReason(""); setNote(""); } });
  };
  return (
    <form className="mb-4 grid gap-3 rounded-lg border border-line p-3" onSubmit={submit}>
      <h4 className="title-section">Book for a member</h4>
      <p className="text-xs text-muted">Active membership and current waiver are required. Members can book ahead.</p>
      <fieldset className="grid gap-3 sm:grid-cols-2" disabled={create.isPending}>
        <label className="grid gap-1 text-sm sm:col-span-2">Member
          <select className="desk-input" required value={memberId} onChange={(event) => { setMemberId(event.target.value); setAnswers({}); setErrors({}); setReason(""); }}>
            <option value="">{members.isLoading ? "Loading members…" : "Select a member"}</option>
            {members.data?.results.map((member) => <option key={member.member_id} value={member.member_id}>{member.display_name}</option>)}
          </select>
        </label>
        <div className="flex gap-2 sm:col-span-2">
          <button className="desk-button" type="button" disabled={!members.data?.previous} onClick={() => { setPage(page - 1); setMemberId(""); }}>Previous members</button>
          <button className="desk-button" type="button" disabled={!members.data?.next} onClick={() => { setPage(page + 1); setMemberId(""); }}>Next members</button>
        </div>
        <label className="grid gap-1 text-sm">Starts (your local time)<input className="desk-input" type="datetime-local" required value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label className="grid gap-1 text-sm">Ends (your local time)<input className="desk-input" type="datetime-local" required value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        {recurringEnabled ? <div className="grid gap-2 sm:col-span-2"><label className="flex gap-2 text-sm"><input type="checkbox" checked={repeat} onChange={(event) => setRepeat(event.target.checked)} />Repeat weekly in makerspace local time</label>{repeat ? <><label className="grid gap-1 text-sm">Occurrences<input className="desk-input" type="number" min={2} max={52} value={count} onChange={(event) => setCount(Number(event.target.value))} /></label><label className="grid gap-1 text-sm">Weeks between bookings<input className="desk-input" type="number" min={1} max={12} value={intervalWeeks} onChange={(event) => setIntervalWeeks(Number(event.target.value))} /></label><p className="text-xs text-muted">Each occurrence is booked and charged separately. The result lists every conflict.</p></> : null}</div> : null}
        <label className="grid gap-1 text-sm sm:col-span-2">Staff note<textarea className="desk-input" maxLength={5000} value={note} onChange={(event) => setNote(event.target.value)} /></label>
        {space.machine_type ? <label className="grid gap-1 text-sm sm:col-span-2">Certification override reason (optional)
          <input className="desk-input" maxLength={1000} value={reason} onChange={(event) => setReason(event.target.value)} />
          <span className="text-xs text-muted">Only staff with authority over this machine type may override. Every override is audited.</span>
        </label> : null}
      </fieldset>
      <CustomFormFields schema={space.custom_form} answers={answers} onChange={setAnswers} disabled={create.isPending} errors={{ ...errors, ...customAnswerErrors(create.error instanceof StructuredApiError ? create.error.body.custom_answers : undefined) }} />
      {members.error || create.error ? <p className="text-sm text-danger" role="alert">{(create.error ?? members.error)?.message}</p> : null}
      <button className="desk-button-primary w-fit" type="submit" disabled={!memberId || create.isPending}>{create.isPending ? "Booking…" : "Create booking"}</button>
      {create.data && "occurrences" in create.data ? <ul className="grid gap-2 text-sm" aria-label="Recurring booking results">{create.data.occurrences.map((row) => <li key={row.occurrence}>{row.occurrence}: {new Date(row.starts_at).toLocaleString()} — {row.booking_id ? row.status : `Conflict: ${row.detail}`}</li>)}</ul> : create.isSuccess ? <p className="text-sm text-success" role="status">Booking created.</p> : null}
    </form>
  );
}
