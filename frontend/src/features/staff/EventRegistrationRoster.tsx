import { useState } from "react";

import { Skeleton, StatusBadge } from "../../components/ui";
import EventCheckInScanner from "./EventCheckInScanner";
import { EventRegisterMember } from "./EventRegisterMember";
import { PaymentReconcileActions } from "./PaymentReconcileActions";
import { useCorrectAttendance } from "./eventFeedbackApi";
import {
  useApproveEventRegistration,
  useEventRegistrations,
  useMarkEventAttended,
  usePromoteEventRegistration,
  useRejectEventRegistration,
  type StaffEvent,
} from "./eventsApi";
import { eventErrorText } from "./eventUi";

export function EventRegistrationRoster({ event, makerspaceId }: {
  event: StaffEvent;
  makerspaceId: number;
}) {
  const [page, setPage] = useState(1);
  const [scanning, setScanning] = useState(false);
  const rows = useEventRegistrations(event.id, page);
  const approve = useApproveEventRegistration(makerspaceId, event.id);
  const reject = useRejectEventRegistration(makerspaceId, event.id);
  const promote = usePromoteEventRegistration(makerspaceId, event.id);
  const attended = useMarkEventAttended(makerspaceId, event.id);
  const correct = useCorrectAttendance(makerspaceId, event.id);

  function pendingFor(registrationId: number) {
    return [approve, reject, promote, attended, correct].some(
      (mutation) => mutation.isPending && mutation.variables === registrationId,
    );
  }

  function errorFor(registrationId: number) {
    return [approve, reject, promote, attended, correct].find(
      (mutation) => mutation.error && mutation.variables === registrationId,
    )?.error;
  }

  const fallbackCount = Object.values(event.registration_counts).reduce((sum, value) => sum + value, 0);
  const checkable = event.status === "published" || event.status === "completed";

  return <section aria-labelledby="registrations-title">
    <h3 id="registrations-title" className="title-section mb-2">Registrations <span className="font-mono">({rows.data?.count ?? fallbackCount})</span></h3>
    {rows.isLoading ? <Skeleton className="h-32 w-full" /> : null}
    {rows.error ? <p className="text-sm text-danger">{eventErrorText(rows.error)}</p> : null}
    {rows.data && !rows.data.results.length ? <p className="text-sm text-muted">No registrations yet.</p> : null}
    <EventRegisterMember makerspaceId={makerspaceId} eventId={event.id} customForm={event.custom_form} disabled={event.status !== "published" || !event.registration_open} />
    {checkable ? (scanning
      ? <EventCheckInScanner makerspaceId={makerspaceId} eventId={event.id} onClose={() => setScanning(false)} />
      : <button className="desk-button mt-3" type="button" onClick={() => setScanning(true)}>Scan check-in</button>
    ) : null}
    {rows.data?.results.length ? <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Event registration contact details</caption><thead><tr><th className="eyebrow p-2">Name</th><th className="eyebrow p-2">Contact</th><th className="eyebrow p-2">Status</th><th className="eyebrow p-2">Action</th></tr></thead><tbody>
      {rows.data.results.map((row) => {
        const pending = pendingFor(row.id);
        const rowError = errorFor(row.id);
        const hasAction = row.status === "pending_approval"
          || (row.status === "waitlisted" && event.registration_requires_approval)
          || (row.status === "registered" && checkable)
          || row.status === "attended";
        return <tr key={row.id} className="border-t border-line">
          <td className="p-2">{row.name}<PaymentReconcileActions makerspaceId={makerspaceId} payment={row.payment} invalidateKeys={[["event", event.id, "registrations"], ["event", event.id], ["events", makerspaceId]]} /></td>
          <td className="p-2"><a className="block hover:underline" href={`mailto:${row.email}`}>{row.email}</a><a className="block text-muted hover:underline" href={`tel:${row.phone}`}>{row.phone}</a></td>
          <td className="p-2"><StatusBadge status={row.status} /></td>
          <td className="p-2"><div className="flex flex-wrap gap-2">
            {row.status === "pending_approval" ? <><button className="desk-button-success" type="button" disabled={pending} onClick={() => approve.mutate(row.id)}>Approve</button><button className="desk-button-danger" type="button" disabled={pending} onClick={() => reject.mutate(row.id)}>Reject</button></> : null}
            {row.status === "waitlisted" && event.registration_requires_approval ? <><button className="desk-button-success" type="button" disabled={pending} onClick={() => promote.mutate(row.id)}>Promote</button><button className="desk-button-danger" type="button" disabled={pending} onClick={() => reject.mutate(row.id)}>Reject</button></> : null}
            {row.status === "registered" && checkable ? <button className="desk-button-success" type="button" disabled={pending} onClick={() => attended.mutate(row.id)}>Mark attended</button> : null}
            {row.status === "attended" ? <button className="desk-button-danger" type="button" disabled={pending} onClick={() => correct.mutate(row.id)}>Correct attendance</button> : null}
            {!hasAction ? "—" : null}
          </div>{rowError ? <p className="mt-1 text-xs text-danger" role="alert">{eventErrorText(rowError)}</p> : null}</td>
        </tr>;
      })}
    </tbody></table></div> : null}
    <div className="mt-3 flex items-center justify-between gap-2"><span className="font-mono text-xs text-muted">Page {page}</span><div className="flex gap-2"><button className="desk-button" type="button" disabled={!rows.data?.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><button className="desk-button" type="button" disabled={!rows.data?.next} onClick={() => setPage((value) => value + 1)}>Next</button></div></div>
  </section>;
}
