"""Pure time math: no database; real IANA transitions, including non-hour DST."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.makerspaces.local_time import (
    is_open, local_day_bounds, local_now, next_open_interval, to_local,
)
from apps.makerspaces.profile_validation import WEEKDAYS


def space(zone="America/New_York", weekly=None, exceptions=None):
    hours = {} if weekly is None and exceptions is None else {
        "weekly": weekly or {}, "exceptions": exceptions or {},
    }
    return SimpleNamespace(timezone=zone, opening_hours=hours)


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def week(day="sun", intervals=None):
    return {key: (intervals or []) if key == day else [] for key in WEEKDAYS}


@pytest.mark.parametrize("zone,day,hours", [
    ("UTC", "2024-03-10", 24), ("Asia/Kolkata", "2024-03-10", 24),
    ("America/New_York", "2024-03-10", 23),
    ("America/New_York", "2024-11-03", 25),
    ("Europe/Berlin", "2024-03-31", 23), ("Europe/Berlin", "2024-10-27", 25),
    ("Australia/Lord_Howe", "2024-10-06", 23.5),
    ("Australia/Lord_Howe", "2024-04-07", 24.5),
    ("America/Santiago", "2024-09-08", 23),
    ("Pacific/Apia", "2011-12-30", 0),
])
def test_local_day_bounds_cover_real_dst_days(zone, day, hours):
    start, end = local_day_bounds(space(zone), date.fromisoformat(day))
    assert start.tzinfo is timezone.utc and end.tzinfo is timezone.utc
    assert (end - start).total_seconds() == hours * 3600


@pytest.mark.parametrize("day", ["2024-03-10", "2024-11-03", "2025-03-09", "2025-11-02"])
def test_day_bounds_contain_exactly_the_local_date_across_transitions(day):
    lab = space()
    local_date = date.fromisoformat(day)
    start, end = local_day_bounds(lab, local_date)
    for minutes in range(-120, 27 * 60, 5):
        at = start + timedelta(minutes=minutes)
        assert (start <= at < end) == (to_local(lab, at).date() == local_date)


def test_to_local_retains_fold_and_instant():
    lab = space()
    first = to_local(lab, instant("2024-11-03T05:30:00Z"))
    second = to_local(lab, instant("2024-11-03T06:30:00Z"))
    assert first.hour == second.hour == 1
    assert (first.fold, second.fold) == (0, 1)
    assert first.astimezone(timezone.utc) == instant("2024-11-03T05:30:00Z")
    assert second.astimezone(timezone.utc) == instant("2024-11-03T06:30:00Z")


def test_local_now_uses_the_makerspace_zone():
    now = local_now(space("Asia/Kolkata"))
    assert now.utcoffset() == timedelta(hours=5, minutes=30)
    assert abs((now.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()) < 5


@pytest.mark.parametrize("call", [
    lambda lab, dt: to_local(lab, dt), lambda lab, dt: is_open(lab, dt),
    lambda lab, dt: next_open_interval(lab, dt),
])
def test_naive_instants_are_rejected(call):
    with pytest.raises(ValueError, match="aware datetime"):
        call(space(), datetime(2024, 1, 1))


def test_fold_opens_first_occurrence_and_closes_last_half_open():
    lab = space(weekly=week(intervals=[{"start": "01:15", "end": "01:45"}]))
    bounds = (instant("2024-11-03T05:15:00Z"), instant("2024-11-03T06:45:00Z"))
    assert next_open_interval(lab, bounds[0] - timedelta(seconds=1)) == bounds
    for minutes in range(-15, 106):
        at = bounds[0] + timedelta(minutes=minutes)
        assert is_open(lab, at) == (bounds[0] <= at < bounds[1])
    assert next_open_interval(lab, instant("2024-11-03T06:30:00Z")) == bounds


@pytest.mark.parametrize("zone,after,expected", [
    ("America/New_York", "2024-03-10T00:00:00Z", ("2024-03-10T07:30:00Z", "2024-03-10T08:00:00Z")),
    ("Australia/Lord_Howe", "2024-10-05T12:00:00Z", ("2024-10-05T15:30:00Z", "2024-10-05T17:00:00Z")),
])
def test_gap_moves_opening_forward_by_gap(zone, after, expected):
    start = "02:30" if zone == "America/New_York" else "02:00"
    lab = space(zone, weekly=week(intervals=[{"start": start, "end": "04:00"}]))
    bounds = tuple(map(instant, expected))
    assert next_open_interval(lab, instant(after)) == bounds
    assert not is_open(lab, bounds[0] - timedelta(seconds=1))
    assert is_open(lab, bounds[0]) and not is_open(lab, bounds[1])


def test_interval_wholly_in_spring_gap_collapses():
    lab = space(weekly=week(intervals=[{"start": "02:00", "end": "03:00"}]))
    assert not is_open(lab, instant("2024-03-10T07:00:00Z"))
    assert next_open_interval(lab, instant("2024-03-10T00:00:00Z"))[0].date() == date(2024, 3, 17)


def test_overlapping_fold_expansion_merges_intervals():
    lab = space(weekly=week(intervals=[{"start": "01:00", "end": "01:15"}, {"start": "01:30", "end": "02:00"}]))
    assert next_open_interval(lab, instant("2024-11-03T04:00:00Z")) == (
        instant("2024-11-03T05:00:00Z"), instant("2024-11-03T07:00:00Z"))


def test_empty_hours_always_open_and_holiday_exception_replaces_day():
    lab = space("Asia/Kolkata", exceptions={"2024-01-01": []})
    assert not is_open(lab, instant("2024-01-01T04:00:00Z"))
    assert next_open_interval(lab, instant("2024-01-01T04:00:00Z")) == local_day_bounds(lab, date(2024, 1, 2))
    assert is_open(space("UTC"), instant("2024-01-01T04:00:00Z"))


def test_closed_week_and_far_future_special_opening():
    lab = space("UTC", weekly=week(), exceptions={"2035-06-01": [{"start": "10:00", "end": "12:00"}]})
    assert next_open_interval(lab, instant("2024-01-01T00:00:00Z")) == (
        instant("2035-06-01T10:00:00Z"), instant("2035-06-01T12:00:00Z"))
    assert next_open_interval(lab, instant("2035-06-01T12:00:00Z")) is None


def test_multiple_intervals_and_exceptions_override_weekly():
    lab = space("UTC", weekly=week("mon", [{"start": "09:00", "end": "12:00"}, {"start": "13:00", "end": "17:00"}]),
                exceptions={"2024-01-08": [{"start": "18:00", "end": "24:00"}]})
    assert not is_open(lab, instant("2024-01-01T12:00:00Z"))
    assert next_open_interval(lab, instant("2024-01-01T12:00:00Z"))[0] == instant("2024-01-01T13:00:00Z")
    assert not is_open(lab, instant("2024-01-08T09:00:00Z"))
    assert is_open(lab, instant("2024-01-08T23:59:59Z"))
    assert not is_open(lab, instant("2024-01-09T00:00:00Z"))


def test_skipped_date_does_not_produce_an_open_interval():
    lab = space("Pacific/Apia", weekly=week(), exceptions={"2011-12-30": [{"start": "00:00", "end": "24:00"}]})
    assert next_open_interval(lab, instant("2011-12-29T00:00:00Z")) is None


def test_far_exception_near_max_date_does_not_overflow_weekly_search():
    lab = space("UTC", weekly=week(), exceptions={"9999-12-30": [{"start": "10:00", "end": "12:00"}]})
    assert next_open_interval(lab, instant("2024-01-01T00:00:00Z")) == (
        instant("9999-12-30T10:00:00Z"), instant("9999-12-30T12:00:00Z"))


@pytest.mark.parametrize("after", ["2024-03-09T12:00:00Z", "2024-03-03T09:00:00Z"])
def test_search_reaches_second_cycle_when_dst_erases_next_weekly_opening(after):
    lab = space(weekly=week(intervals=[{"start": "02:00", "end": "03:00"}]))
    assert next_open_interval(lab, instant(after)) == (
        instant("2024-03-17T06:00:00Z"), instant("2024-03-17T07:00:00Z"))


def test_search_crosses_holiday_closures_longer_than_a_week():
    first = date(2024, 1, 1)
    exceptions = {(first + timedelta(days=offset)).isoformat(): [] for offset in range(30)}
    lab = space("UTC", weekly=week("mon", [{"start": "09:00", "end": "17:00"}]),
                exceptions=exceptions)
    assert next_open_interval(lab, instant("2024-01-01T00:00:00Z")) == (
        instant("2024-02-05T09:00:00Z"), instant("2024-02-05T17:00:00Z"))
