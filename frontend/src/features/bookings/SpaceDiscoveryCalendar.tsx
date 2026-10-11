import { MonthCalendar } from "../discovery/MonthCalendar";
import { monthWindow } from "../discovery/useDiscoveryState";
import { dayStart } from "../discovery/calendarDates";
import { usePublicAvailability, type PublicBookableSpace } from "./publicBookingsApi";

export function SpaceDiscoveryCalendar({ slug, space, month, timeZone = "UTC" }: { slug: string; space: PublicBookableSpace; month: string; timeZone?: string }) {
  const { start, end } = monthWindow(month, timeZone);
  // The API caps each window at exactly 31 days. A local 31-day month with a
  // daylight-saving fallback is longer, so split only that case and deduplicate
  // bookings that overlap the boundary. Both windows must succeed before display.
  const split = end.getTime() - start.getTime() > 31 * 24 * 60 * 60 * 1000;
  const [year, number] = month.split("-").map(Number);
  const midpoint = dayStart(year, number, 16, timeZone);
  const future = end.getTime() > Date.now();
  const enabled = space.show_public_availability && future;
  const availability = usePublicAvailability(slug, space.public_token, start.toISOString(), (split ? midpoint : end).toISOString(), enabled);
  const remainder = usePublicAvailability(slug, space.public_token, midpoint.toISOString(), end.toISOString(), enabled && split);
  if (!space.show_public_availability || availability.data?.availability === null || (split && remainder.data?.availability === null)) return <p className="mt-4 text-sm text-muted">Availability is not published. Submit a time for the makerspace to check.</p>;
  if (!future) return <p className="mt-4 text-sm text-muted">Choose the current month or a later month to check upcoming availability.</p>;
  if (availability.isLoading || (split && remainder.isLoading)) return <p role="status" className="mt-4 text-sm text-muted">Loading published bookings...</p>;
  if (availability.error || (split && remainder.error)) return <div role="alert" className="mt-4"><p className="text-sm text-danger">Availability could not be checked. This does not mean the space is free.</p><button type="button" className="desk-button" onClick={() => { void availability.refetch(); if (split) void remainder.refetch(); }}>Retry availability</button></div>;
  if (!availability.data || (split && !remainder.data)) return null;
  const combined = [...(availability.data.availability ?? []), ...(split ? remainder.data?.availability ?? [] : [])];
  const intervals = [...new Map(combined.map((interval) => [`${interval.starts_at}-${interval.ends_at}`, interval])).values()];
  return <div className="mt-5">
    <p className="mb-3 text-sm text-muted">Confirmed bookings only. Empty dates do not guarantee a bookable time; rules are checked when you submit.</p>
    {!intervals.length ? <p className="mb-3 text-sm text-muted">No confirmed bookings are published in this month.</p> : null}
    <MonthCalendar month={month} timeZone={timeZone} label={`${space.name} published bookings`} entries={intervals.map((interval, index) => ({
      id: `${interval.starts_at}-${index}`, startsAt: interval.starts_at, endsAt: interval.ends_at,
      label: `Booked ${new Date(interval.starts_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone })}–${new Date(interval.ends_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone })}${space.show_public_booker_names && interval.booker_name ? ` · ${interval.booker_name}` : ""}`,
    }))} />
  </div>;
}
