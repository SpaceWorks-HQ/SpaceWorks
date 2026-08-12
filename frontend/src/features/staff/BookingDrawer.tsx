import { useState } from "react";

import { ConfirmDialog, DetailDrawer, EmptyState, Skeleton, StatusBadge } from "../../components/ui";
import { CustomAnswersView } from "../forms/CustomAnswersView";
import { BookableSpaceForm, valuesForSpace } from "./BookableSpaceForm";
import {
  useBookableSpace,
  useBookingAction,
  useDeactivateBookableSpace,
  useSpaceBookings,
  useUpdateBookableSpace,
  type Booking,
  type BookingAction,
  type BookingFilters,
} from "./bookingsApi";
import { PaymentReconcileActions } from "./PaymentReconcileActions";

type PendingAction = { booking: Booking; action: BookingAction };

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong.";
}

function bookingTime(booking: Booking) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${format.format(new Date(booking.starts_at))} – ${format.format(new Date(booking.ends_at))}`;
}

function actionLabel(action: BookingAction) {
  return {
    approve: "Approve",
    reject: "Reject",
    cancel: "Cancel booking",
    complete: "Complete",
    "no-show": "Mark no-show",
  }[action];
}

export function BookingDrawer({ makerspaceId, spaceId, onClose }: {
  makerspaceId: number;
  spaceId: number;
  onClose: () => void;
}) {
  const spaceQuery = useBookableSpace(spaceId);
  const space = spaceQuery.data;
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<BookingFilters>({});
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const bookings = useSpaceBookings(spaceId, filters, page);
  const update = useUpdateBookableSpace(makerspaceId, spaceId);
  const deactivate = useDeactivateBookableSpace(makerspaceId, spaceId);
  const action = useBookingAction(makerspaceId, spaceId);

  const setFilter = <K extends keyof BookingFilters>(key: K, value: BookingFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };
  const actionError = update.error || deactivate.error || action.error;

  return (
    <>
      <DetailDrawer open title={space?.name ?? "Space details"} onClose={onClose}>
        {spaceQuery.isLoading ? <Skeleton className="h-64 w-full" /> : null}
        {spaceQuery.error ? <EmptyState title="Unable to load space" description={errorText(spaceQuery.error)} /> : null}
        {space ? (
          <div className="grid gap-6">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={space.is_active ? "active" : "inactive"} />
              <span className="text-sm text-muted">{space.effective_requester_notifications_enabled ? "Requester emails on" : "Requester emails off"}</span>
            </div>
            <BookableSpaceForm
              key={space.updated_at}
              initialValues={valuesForSpace(space)}
              onSubmit={(payload) => update.mutate(payload)}
              pending={update.isPending}
              error={update.error ? errorText(update.error) : undefined}
              submitLabel="Save changes"
              disabled={!space.is_active}
            />
            {space.is_active ? <button className="desk-button-danger w-fit" type="button" onClick={() => setConfirmDeactivate(true)}>Deactivate space</button> : <p className="text-sm text-muted">This space is inactive and read-only.</p>}
            <section aria-labelledby="space-bookings-title">
              <div className="mb-3">
                <h3 id="space-bookings-title" className="title-section">Bookings <span className="font-mono">({bookings.data?.count ?? 0})</span></h3>
                <p className="mt-1 text-xs text-muted">Contact details and custom answers are staff-only.</p>
              </div>
              <div className="mb-3 grid gap-2 sm:grid-cols-3">
                <label className="grid gap-1 text-xs font-semibold text-muted">Status
                  <select className="desk-input" value={filters.status ?? ""} onChange={(event) => setFilter("status", event.target.value as BookingFilters["status"])}>
                    <option value="">All statuses</option>
                    <option value="pending">Pending</option>
                    <option value="confirmed">Confirmed</option>
                    <option value="rejected">Rejected</option>
                    <option value="cancelled">Cancelled</option>
                    <option value="completed">Completed</option>
                    <option value="no_show">No-show</option>
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold text-muted">Starts after
                  <input className="desk-input" type="datetime-local" value={filters.starts_at ?? ""} onChange={(event) => setFilter("starts_at", event.target.value)} />
                </label>
                <label className="grid gap-1 text-xs font-semibold text-muted">Ends before
                  <input className="desk-input" type="datetime-local" value={filters.ends_at ?? ""} onChange={(event) => setFilter("ends_at", event.target.value)} />
                </label>
              </div>
              {bookings.isLoading ? <Skeleton className="h-40 w-full" /> : null}
              {bookings.error ? <p className="text-sm text-danger" role="alert">{errorText(bookings.error)}</p> : null}
              {bookings.data && !bookings.data.results.length ? <EmptyState title="No matching bookings" description="Bookings for this space will appear here." /> : null}
              {bookings.data?.results.length ? (
                <div className="grid gap-3">
                  {bookings.data.results.map((booking) => (
                    <article className="rounded-xl border border-line bg-bg p-3" key={booking.id}>
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div><h4 className="title-section">{booking.name}</h4><p className="mt-1 font-mono text-xs text-muted">{bookingTime(booking)}</p></div>
                        <StatusBadge status={booking.status} />
                      </div>
                      <div className="mt-2 text-sm"><a className="block break-all hover:underline" href={"mailto:" + booking.email}>{booking.email}</a><a className="block text-muted hover:underline" href={"tel:" + booking.phone}>{booking.phone}</a></div>
                      <details className="mt-3 rounded-lg border border-line bg-panel p-3">
                        <summary className="cursor-pointer text-sm font-semibold text-ink">View custom answers</summary>
                        <div className="mt-3"><CustomAnswersView snapshot={booking.custom_answers} /></div>
                      </details>
                      <PaymentReconcileActions
                        makerspaceId={makerspaceId}
                        payment={booking.payment}
                        invalidateKeys={[
                          ["booking-space", spaceId, "bookings"],
                          ["booking-space", spaceId],
                        ]}
                      />
                      <BookingActions booking={booking} onAction={(nextAction) => setPendingAction({ booking, action: nextAction })} />
                    </article>
                  ))}
                </div>
              ) : null}
              {bookings.data ? <div className="mt-3 flex items-center justify-between gap-2"><span className="font-mono text-xs text-muted">Page {page}</span><div className="flex gap-2"><button className="desk-button" type="button" disabled={!bookings.data.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</button><button className="desk-button" type="button" disabled={!bookings.data.next} onClick={() => setPage((value) => value + 1)}>Next</button></div></div> : null}
            </section>
            {actionError ? <p className="text-sm text-danger" role="alert">{errorText(actionError)}</p> : null}
          </div>
        ) : null}
      </DetailDrawer>
      <ConfirmDialog
        open={pendingAction !== null}
        title={pendingAction ? actionLabel(pendingAction.action) : "Update booking"}
        message={pendingAction ? actionLabel(pendingAction.action) + " for " + pendingAction.booking.name + "?" : ""}
        confirmLabel={pendingAction ? actionLabel(pendingAction.action) : "Confirm"}
        tone={pendingAction?.action === "approve" || pendingAction?.action === "complete" ? "default" : "danger"}
        pending={action.isPending}
        onCancel={() => setPendingAction(null)}
        onConfirm={() => pendingAction && action.mutate({ bookingId: pendingAction.booking.id, action: pendingAction.action }, { onSuccess: () => setPendingAction(null), onError: () => setPendingAction(null) })}
      />
      <ConfirmDialog open={confirmDeactivate} title="Deactivate space" message="The public page will hide this space and no new bookings can be submitted or approved." confirmLabel="Deactivate" tone="danger" pending={deactivate.isPending} onCancel={() => setConfirmDeactivate(false)} onConfirm={() => deactivate.mutate(undefined, { onSuccess: () => setConfirmDeactivate(false), onError: () => setConfirmDeactivate(false) })} />
    </>
  );
}

function BookingActions({ booking, onAction }: { booking: Booking; onAction: (action: BookingAction) => void }) {
  const ended = new Date(booking.ends_at) <= new Date();
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {booking.status === "pending" ? <><button className="desk-button-success" type="button" onClick={() => onAction("approve")}>Approve</button><button className="desk-button-danger" type="button" onClick={() => onAction("reject")}>Reject</button></> : null}
      {booking.status === "confirmed" ? <button className="desk-button-danger" type="button" onClick={() => onAction("cancel")}>Cancel</button> : null}
      {booking.status === "confirmed" && ended ? <><button className="desk-button-success" type="button" onClick={() => onAction("complete")}>Complete</button><button className="desk-button-warn" type="button" onClick={() => onAction("no-show")}>No-show</button></> : null}
    </div>
  );
}
