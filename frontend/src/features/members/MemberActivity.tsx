import { useEffect, useState } from "react";

import { staffRequestBlob } from "../../lib/api";
import { MemberEventFeedback } from "./MemberEventFeedback";

type Loan = { label: string; checked_out_at: string; due_at: string | null; overdue: boolean };
type MachineServiceRequest = { machine_type?: string; title: string; status: string; queue_position: number | null };
type Booking = { space_name: string; starts_at: string; ends_at: string; status: string };
type Registration = {
  registration_id: number;
  event_title: string;
  starts_at: string;
  status: string;
  waitlist_position: number | null;
  // Non-null only for a REGISTERED row: a waitlisted registration has nothing confirmable
  // behind it, and a QR that scans and then fails is worse than no QR at all.
  checkin_token: string | null;
  feedback_available: boolean;
  feedback_path: string | null;
  certificate: { id: number; status: string; revision: number } | null;
};
type Presence = { started_at: string; expires_at: string; active: boolean };

export type MemberActivity = {
  active_hardware_loans: Loan[];
  machine_service_requests?: MachineServiceRequest[];
  bookings?: { upcoming: Booking[]; past: Booking[] };
  event_registrations?: Registration[];
  recent_presence_sessions: Presence[];
  currently_checked_in: boolean;
  accountability: { membership_active: boolean; waiver_acceptance_required: boolean; restriction_code: string | null };
};

/** The member's own check-in QR, fetched rather than linked.
 *
 * `<img src>` cannot carry an Authorization header, so the SVG is fetched through the
 * refresh-aware authenticated path and handed to the DOM as an object URL. That URL is
 * revoked on unmount and whenever it is replaced -- otherwise every open-and-close leaks a
 * blob for the lifetime of the tab.
 */
function CheckInQr({ makerspaceId, registrationId }: { makerspaceId: number; registrationId: number }) {
  const [open, setOpen] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let url: string | null = null;
    staffRequestBlob(
      `/member/makerspaces/${makerspaceId}/event-registrations/${registrationId}/qr`,
    )
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load your code.");
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [open, makerspaceId, registrationId]);

  return <div className="mt-1">
    <button
      type="button"
      className="desk-button-ghost"
      aria-expanded={open}
      onClick={() => { setError(null); setOpen((value) => !value); }}
    >
      {open ? "Hide check-in QR" : "Show check-in QR"}
    </button>
    {/* Unmounted rather than hidden, so the blob is released and keyboard users cannot tab
        into an image that is not on screen. */}
    {open && src ? <img src={src} alt="Your check-in QR code" className="mt-2 max-w-[220px]" /> : null}
    {open && error ? <p className="mt-2 text-sm text-danger">{error}</p> : null}
  </div>;
}

const SECTION_TONES: Record<string, string> = {
  "My activity": "border-secondary",
  "Active hardware loans": "border-success",
  "3D print requests": "border-accent",
  "Machine-service requests": "border-warn",
  Bookings: "border-secondary",
  "Event registrations": "border-accent",
  "Recent presence": "border-success",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) { return <section className={`desk-panel ${SECTION_TONES[title] ?? "border-secondary"} p-5`}><h2 className="title-panel">{title}</h2>{children}</section>; }
function Empty({ children = "Nothing to show yet." }: { children?: React.ReactNode }) { return <p className="mt-2 border-l-2 border-secondary pl-3 text-sm text-muted">{children}</p>; }
const REGISTRATION_LABELS: Record<string, string> = {
  pending_approval: "Awaiting approval",
  registered: "Confirmed",
  waitlisted: "Waitlisted",
  rejected: "Not approved",
  cancelled: "Cancelled",
  attended: "Attended",
};

export function MemberActivityPanel({ activity, makerspaceId, makerspaceSlug }: { activity: MemberActivity; makerspaceId: number; makerspaceSlug: string }) {
  const printerRequests = (activity.machine_service_requests ?? []).filter((request) => request.machine_type === "3d_printer");
  const otherServiceRequests = (activity.machine_service_requests ?? []).filter((request) => request.machine_type !== "3d_printer");
  const requestRows = (rows: MachineServiceRequest[]) => rows.length ? <ul className="mt-3 space-y-2 text-sm text-muted">{rows.map((item) => <li key={`${item.title}-${item.status}`}><span className="font-medium text-ink">{item.title}</span> · {item.status}{item.queue_position ? <span className="font-mono">{` · Queue ${item.queue_position}`}</span> : ""}</li>)}</ul> : <Empty />;
  return <div className="space-y-5">
    <Section title="My activity"><p className="mt-1 text-sm text-muted">{activity.currently_checked_in ? "You are currently checked in." : "You are not currently checked in."}</p>{activity.accountability.waiver_acceptance_required ? <p className="mt-2 text-sm text-danger">Accept the current waiver before making facility requests.</p> : null}</Section>
    <Section title="Active hardware loans">{activity.active_hardware_loans.length ? <ul className="mt-3 space-y-2 text-sm text-muted">{activity.active_hardware_loans.map((loan) => <li key={`${loan.label}-${loan.checked_out_at}`}><span className="font-medium text-ink">{loan.label}</span><span className="font-mono">{loan.due_at ? ` · Due ${new Date(loan.due_at).toLocaleString()}` : " · No due date"}</span>{loan.overdue ? " · Overdue" : ""}</li>)}</ul> : <Empty />}</Section>
    {activity.machine_service_requests ? <><Section title="3D print requests">{requestRows(printerRequests)}</Section>{otherServiceRequests.length ? <Section title="Machine-service requests">{requestRows(otherServiceRequests)}</Section> : null}</> : null}
    {activity.bookings ? <Section title="Bookings"><div className="mt-3 grid gap-4 sm:grid-cols-2"><div><h3 className="title-section">Upcoming</h3>{activity.bookings.upcoming.length ? <ul className="mt-2 space-y-2 text-sm text-muted">{activity.bookings.upcoming.map((item) => <li key={`${item.space_name}-${item.starts_at}`}>{item.space_name} · <span className="font-mono">{new Date(item.starts_at).toLocaleString()}</span> · {item.status}</li>)}</ul> : <Empty />}</div><div><h3 className="title-section">Past</h3>{activity.bookings.past.length ? <ul className="mt-2 space-y-2 text-sm text-muted">{activity.bookings.past.map((item) => <li key={`${item.space_name}-${item.starts_at}`}>{item.space_name} · <span className="font-mono">{new Date(item.starts_at).toLocaleString()}</span> · {item.status}</li>)}</ul> : <Empty />}</div></div></Section> : null}
    {activity.event_registrations ? <Section title="Event registrations">{activity.event_registrations.length ? <ul className="mt-3 space-y-2 text-sm text-muted">{activity.event_registrations.map((item) => <li key={item.registration_id}><span className="font-medium text-ink">{item.event_title}</span> · {REGISTRATION_LABELS[item.status] ?? item.status}{item.status === "pending_approval" ? " · No payment until confirmed" : ""}{item.waitlist_position ? ` · Waitlist ${item.waitlist_position}` : ""}{item.checkin_token ? <CheckInQr makerspaceId={makerspaceId} registrationId={item.registration_id} /> : null}<MemberEventFeedback makerspaceId={makerspaceId} makerspaceSlug={makerspaceSlug} registrationId={item.registration_id} feedbackPath={item.feedback_path} certificate={item.certificate} /></li>)}</ul> : <Empty />}</Section> : null}
    <Section title="Recent presence">{activity.recent_presence_sessions.length ? <ul className="mt-3 space-y-2 font-mono text-sm text-muted">{activity.recent_presence_sessions.map((item) => <li key={item.started_at}>{new Date(item.started_at).toLocaleString()} to {new Date(item.expires_at).toLocaleString()}{item.active ? " · Active" : ""}</li>)}</ul> : <Empty />}</Section>
  </div>;
}
