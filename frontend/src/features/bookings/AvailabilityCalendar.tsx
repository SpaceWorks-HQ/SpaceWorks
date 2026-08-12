import { useMemo, useState } from "react";

import { usePublicAvailability } from "./publicBookingsApi";

const WINDOW_DAYS = 14;

function windowDates(offset: number) {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() + offset * WINDOW_DAYS);
  const end = new Date(start);
  end.setDate(end.getDate() + WINDOW_DAYS);
  return { startsAt: start.toISOString(), endsAt: end.toISOString() };
}

function rangeLabel(startsAt: string, endsAt: string) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
  const inclusiveEnd = new Date(new Date(endsAt).getTime() - 1);
  return `${format.format(new Date(startsAt))} – ${format.format(inclusiveEnd)}`;
}

function intervalLabel(startsAt: string, endsAt: string) {
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
  return `${format.format(new Date(startsAt))} – ${format.format(new Date(endsAt))}`;
}

export function AvailabilityCalendar({ makerspaceSlug, publicToken }: {
  makerspaceSlug: string;
  publicToken: string;
}) {
  const [offset, setOffset] = useState(0);
  const window = useMemo(() => windowDates(offset), [offset]);
  const availability = usePublicAvailability(makerspaceSlug, publicToken, window.startsAt, window.endsAt);

  return (
    <section className="rounded-lg border border-secondary bg-secondary/10 p-4" aria-labelledby={"availability-" + publicToken}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id={"availability-" + publicToken} className="title-section">Published availability</h3>
          <p className="eyebrow mt-1 font-mono">{rangeLabel(window.startsAt, window.endsAt)}</p>
        </div>
        <div className="flex gap-2">
          <button className="desk-button-ghost" type="button" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 1))}>Previous 14 days</button>
          <button className="desk-button-ghost" type="button" onClick={() => setOffset((value) => value + 1)}>Next 14 days</button>
        </div>
      </div>
      {availability.isLoading ? <p className="mt-3 text-sm text-muted" aria-live="polite">Checking confirmed bookings...</p> : null}
      {availability.error ? (
        <div className="mt-3" role="alert">
          <p className="text-sm text-danger">Availability could not be checked. This does not mean the space is free.</p>
          <button className="desk-button-ghost mt-2" type="button" onClick={() => availability.refetch()}>Retry</button>
        </div>
      ) : null}
      {availability.data?.availability === null ? (
        <p className="mt-3 text-sm text-muted">Availability is not published. You may still submit your selected time for the makerspace to check.</p>
      ) : null}
      {availability.data?.availability?.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No confirmed bookings are published in this window.</p>
      ) : null}
      {availability.data?.availability?.length ? (
        <ul className="mt-3 grid gap-2">
          {availability.data.availability.map((interval) => (
            <li className="rounded-lg border border-success bg-success/15 px-3 py-2 text-sm text-ink" key={interval.starts_at + interval.ends_at}>
              <time className="font-mono" dateTime={interval.starts_at}>{intervalLabel(interval.starts_at, interval.ends_at)}</time>
              {interval.booker_name !== null ? <span className="ml-2 font-semibold">{interval.booker_name}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
