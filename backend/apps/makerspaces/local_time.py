"""The single local-day boundary service for makerspace consumers.

All instant arguments must be aware; returned interval bounds are UTC and half-open.
Ambiguous openings use the first fold, closings the last. Nonexistent wall times
shift forward by the clock gap. A skipped date has zero-length day bounds. Opening
intervals wholly in a gap may collapse and are ignored. Hours are advisory here:
this module does not impose booking/presence policy.
"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .profile_validation import WEEKDAYS


def _aware(dt):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("An aware datetime is required.")
    return dt.astimezone(timezone.utc)


def to_local(makerspace, dt):
    return _aware(dt).astimezone(ZoneInfo(makerspace.timezone))


def local_now(makerspace):
    return to_local(makerspace, datetime.now(timezone.utc))


def _wall_bound(zone, wall, *, closing=False):
    candidates = [wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                  for fold in (0, 1)]
    valid = [instant for instant in candidates
             if instant.astimezone(zone).replace(tzinfo=None) == wall]
    if valid:
        return max(valid) if closing else min(valid)
    # Round-tripping a nonexistent wall time projects it either side of the gap.
    return min(instant for instant in candidates
               if instant.astimezone(zone).replace(tzinfo=None) > wall)


def local_day_bounds(makerspace, day):
    """UTC [start, end) for a calendar date; DST days can be 23/25 hours (or 0)."""
    zone = ZoneInfo(makerspace.timezone)
    return (_wall_bound(zone, datetime.combine(day, time.min)),
            _wall_bound(zone, datetime.combine(day + timedelta(days=1), time.min)))


def _day_intervals(makerspace, day):
    hours = makerspace.opening_hours or {}
    weekly = hours.get("weekly", {})
    intervals = hours.get("exceptions", {}).get(day.isoformat())
    if intervals is None:
        intervals = weekly.get(WEEKDAYS[day.weekday()], []) if weekly else [{"start": "00:00", "end": "24:00"}]
    zone = ZoneInfo(makerspace.timezone)
    midnight = datetime.combine(day, time.min)
    bounds = []
    for interval in intervals:
        def wall(value):
            hour, minute = map(int, value.split(":"))
            return midnight + timedelta(hours=hour, minutes=minute)
        start = _wall_bound(zone, wall(interval["start"]))
        end = _wall_bound(zone, wall(interval["end"]), closing=True)
        # Keep shifted gap endpoints within their calendar day (e.g. skipped dates).
        day_start, day_end = local_day_bounds(makerspace, day)
        start, end = max(start, day_start), min(end, day_end)
        if start < end:
            bounds.append((start, end))
    # Fold expansion can make otherwise disjoint wall-clock intervals overlap.
    merged = []
    for start, end in sorted(bounds):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def is_open(makerspace, at):
    instant = _aware(at)
    return any(start <= instant < end for start, end in
               _day_intervals(makerspace, to_local(makerspace, at).date()))


def next_open_interval(makerspace, after):
    """First daily interval whose end is after the instant, including an ongoing one.

    Return None for a closed schedule with no future exception. Search work is
    bounded by two weekly cycles and the number of exceptions, not years of dates.
    The second cycle covers a weekly interval erased by a DST gap/skipped date.
    """
    instant = _aware(after)
    first = to_local(makerspace, after).date()
    anchors = {first}
    anchors.update(datetime.fromisoformat(day).date() for day in
                   (makerspace.opening_hours or {}).get("exceptions", {})
                   if day >= first.isoformat())
    days = sorted({anchor + timedelta(days=offset) for anchor in anchors
                   for offset in range(min(15, (date.max - anchor).days))})
    for day in days:
        for start, end in _day_intervals(makerspace, day):
            if end > instant:
                return start, end
    return None
