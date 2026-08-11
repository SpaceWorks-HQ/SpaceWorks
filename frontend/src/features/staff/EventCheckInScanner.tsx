import { useState } from "react";

import QrScanner from "../../components/ui/QrScanner";
import { StructuredApiError } from "../../lib/api";
import {
  useMarkEventAttended,
  useResolveEventCheckIn,
  type EventCheckInResolution,
} from "./eventsApi";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** Staff-side QR check-in: scan, see who it is, then confirm.
 *
 * The two steps are deliberate and must not be collapsed into one. Resolving is read-only
 * and only reports a name; confirming is the mutation. Auto-confirming on scan would mean
 * a mis-aimed camera marks the wrong person present, and attendance is the record a paid
 * event is reconciled against.
 */
export default function EventCheckInScanner({
  makerspaceId,
  eventId,
  onClose,
}: {
  makerspaceId: number;
  eventId: number;
  onClose: () => void;
}) {
  const [scanning, setScanning] = useState(true);
  const [resolved, setResolved] = useState<EventCheckInResolution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const resolve = useResolveEventCheckIn(eventId);
  const attend = useMarkEventAttended(makerspaceId, eventId);

  const handleScan = async (value: string) => {
    setScanning(false);
    setError(null);
    setConfirmed(null);
    setResolved(null);
    try {
      setResolved(await resolve.mutateAsync(value.trim()));
    } catch (cause) {
      // A 404 covers unknown, malformed and wrong-event tokens alike -- the endpoint
      // answers them identically on purpose -- so say the one thing that is true of all
      // three rather than surfacing a bare "not found".
      setError(
        cause instanceof StructuredApiError && cause.status === 404
          ? "That is not a check-in code for this event."
          : cause instanceof Error
            ? cause.message
            : "Could not read that code.",
      );
    }
  };

  const handleConfirm = async () => {
    if (!resolved) return;
    setError(null);
    try {
      await attend.mutateAsync(resolved.registration_id);
      setConfirmed(`${resolved.name} checked in.`);
      setResolved(null);
    } catch (cause) {
      if (cause instanceof StructuredApiError && cause.status === 409) {
        // A conflict is NOT proof of a duplicate check-in. `mark_attended` returns 409 for
        // every non-registered status, so between resolving and confirming another staffer
        // could have cancelled the registration or the whole event. Claiming "already
        // checked in" would then be a false statement made to someone standing at a door,
        // so say what is actually known and force a re-scan rather than leaving a stale
        // resolution with Confirm still enabled.
        setResolved(null);
        setError(
          `${resolved.name} could not be checked in -- the registration changed. Scan again to see its current state.`,
        );
        return;
      }
      setError(cause instanceof Error ? cause.message : "Could not confirm attendance.");
    }
  };

  // Gate on "registered" rather than excluding "waitlisted": `mark-attended` refuses every
  // other status, so an allow-list keeps a cancelled or already-attended code from offering
  // a button that can only fail. Excluding one status at a time is how the cancelled case
  // slipped through and reported a false "already checked in" to someone at the door.
  const confirmable = resolved?.status === "registered" && resolved.confirmable;
  const blockedReason = !resolved || confirmable
    ? null
    : resolved.status === "waitlisted"
      ? "Waitlisted registrations cannot be checked in until they are promoted."
      : resolved.status === "attended"
        ? "This registration is already checked in."
        : resolved.status === "cancelled"
          ? "This registration was cancelled, so it cannot be checked in."
          : resolved.event_status === "cancelled"
            ? "This event was cancelled, so attendance cannot be confirmed."
            : `Attendance cannot be confirmed while this event is ${resolved.event_status}.`;

  return (
    <section
      className="mt-3 rounded-lg border border-line bg-panel p-3"
      aria-labelledby="event-checkin-title"
    >
      <div className="flex items-start justify-between gap-3">
        <h4 id="event-checkin-title" className="font-semibold text-ink">
          Check in by QR
        </h4>
        <button type="button" className={`desk-button ${FOCUS}`} onClick={onClose}>
          Done
        </button>
      </div>

      {resolved ? (
        <div className="mt-3">
          <p className="text-ink">
            <span className="font-medium">{resolved.name}</span> · {resolved.status}
          </p>
          {resolved.payment_status ? (
            // Information only. A payment problem must never stop the door: staff take
            // cash and reconcile later, and a card outage is not a reason to refuse
            // someone entry to an event they registered for.
            <p className="mt-1 text-sm text-muted">Payment: {resolved.payment_status}</p>
          ) : null}
          {resolved.host_waiver_state === "missing" ? (
            // Reported, not enforced. Someone standing at the door with nothing on file is
            // exactly who the host wants to hand a waiver to; refusing them entry is not
            // this screen's job, the same way payment state is shown without blocking.
            <p className="mt-1 text-sm text-muted">
              No host waiver on file — take one at the desk.
            </p>
          ) : null}
          {blockedReason ? (
            <p className="mt-2 text-sm text-danger">{blockedReason}</p>
          ) : null}
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className={`desk-button-primary ${FOCUS}`}
              disabled={!confirmable || attend.isPending}
              onClick={handleConfirm}
            >
              Confirm attendance
            </button>
            <button
              type="button"
              className={`desk-button ${FOCUS}`}
              onClick={() => {
                setResolved(null);
                setScanning(true);
              }}
            >
              Scan another
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-3">
          {confirmed ? <p className="text-sm text-ink">{confirmed}</p> : null}
          <button
            type="button"
            className={`desk-button mt-2 ${FOCUS}`}
            disabled={resolve.isPending}
            onClick={() => {
              setError(null);
              setScanning(true);
            }}
          >
            {resolve.isPending ? "Reading…" : "Scan a code"}
          </button>
        </div>
      )}

      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}

      {/* Unmounted rather than hidden, so the camera stops and keyboard users cannot tab
          into a scanner they cannot see. */}
      {scanning ? (
        <QrScanner onScan={handleScan} onClose={() => setScanning(false)} />
      ) : null}
    </section>
  );
}
