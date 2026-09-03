from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from rest_framework import serializers


MAX_CANDIDATES = 500
MAX_FUTURE_OCCURRENCES = 48
HORIZON_DAYS = 366
MIN_EXTENSION_BUFFER = timedelta(hours=1)
FORBIDDEN_PARTS = frozenset({"DTSTART", "RDATE", "EXDATE"})


@dataclass(frozen=True)
class Occurrence:
    key: str
    local_start: datetime
    starts_at: datetime
    ends_at: datetime


def _timezone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise serializers.ValidationError(
            {"recurrence_timezone": "Use a valid IANA timezone name."},
            code="invalid_recurrence_timezone",
        ) from exc


def normalize_rule(value):
    text = str(value or "").strip().upper()
    if text.startswith("RRULE:"):
        text = text[6:]
    if not text or "\n" in text or "\r" in text:
        raise serializers.ValidationError(
            {"recurrence_rule": "Provide one RFC 5545 RRULE body."},
            code="invalid_recurrence_rule",
        )
    names = {part.partition("=")[0] for part in text.split(";")}
    if names & FORBIDDEN_PARTS or any("=" not in part for part in text.split(";")):
        raise serializers.ValidationError(
            {"recurrence_rule": "DTSTART, RDATE, and EXDATE are not allowed."},
            code="invalid_recurrence_rule",
        )
    return text


def local_anchor(*, local_date, local_time, timezone_name):
    zone = _timezone(timezone_name)
    naive = datetime.combine(local_date, local_time.replace(tzinfo=None))
    return naive.replace(tzinfo=zone, fold=0)


def parsed_rule(*, rule, local_date, local_time, timezone_name):
    normalized = normalize_rule(rule)
    anchor = local_anchor(
        local_date=local_date, local_time=local_time, timezone_name=timezone_name
    )
    try:
        parsed = rrulestr(normalized, dtstart=anchor, forceset=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise serializers.ValidationError(
            {"recurrence_rule": "This recurrence rule is invalid."},
            code="invalid_recurrence_rule",
        ) from exc
    return normalized, parsed, anchor


def validate_series_recurrence(series):
    normalized, parsed, anchor = parsed_rule(
        rule=series.recurrence_rule,
        local_date=series.dtstart_local_date,
        local_time=series.dtstart_local_time,
        timezone_name=series.recurrence_timezone,
    )
    first = parsed.after(anchor, inc=True)
    if first is None:
        raise serializers.ValidationError(
            {"recurrence_rule": "The rule does not produce an occurrence."},
            code="empty_recurrence_rule",
        )
    buffer = list(parsed.xafter(anchor, count=MAX_FUTURE_OCCURRENCES + 1, inc=True))
    if len(buffer) > MAX_FUTURE_OCCURRENCES and buffer[-1] - buffer[0] < MIN_EXTENSION_BUFFER:
        raise serializers.ValidationError(
            {"recurrence_rule": "This rule is too dense for the hourly extension window."},
            code="recurrence_too_dense",
        )
    return normalized


def _is_real_wall_time(value, zone):
    round_trip = value.astimezone(dt_timezone.utc).astimezone(zone)
    return round_trip.replace(tzinfo=None) == value.replace(tzinfo=None)


def occurrences(series, *, now):
    normalized, rule, _anchor = parsed_rule(
        rule=series.recurrence_rule,
        local_date=series.dtstart_local_date,
        local_time=series.dtstart_local_time,
        timezone_name=series.recurrence_timezone,
    )
    zone = _timezone(series.recurrence_timezone)
    duration = timedelta(minutes=series.duration_minutes)
    lower_utc = now - duration
    upper_utc = now + timedelta(days=HORIZON_DAYS)
    lower_local = lower_utc.astimezone(zone)
    results = []
    candidates = 0
    for local_value in rule.xafter(lower_local, count=MAX_CANDIDATES + 1, inc=True):
        candidates += 1
        if candidates > MAX_CANDIDATES:
            raise serializers.ValidationError(
                {"recurrence_rule": "The recurrence is too dense to expand safely."},
                code="recurrence_candidate_limit",
            )
        local_value = local_value.astimezone(zone).replace(fold=0)
        start_utc = local_value.astimezone(dt_timezone.utc)
        if start_utc > upper_utc:
            break
        if not _is_real_wall_time(local_value, zone):
            continue
        if start_utc >= now and sum(row.starts_at >= now for row in results) >= MAX_FUTURE_OCCURRENCES:
            break
        key = f"{series.revision}:{local_value.strftime('%Y%m%dT%H%M%S')}"
        results.append(Occurrence(key, local_value, start_utc, start_utc + duration))
    series.recurrence_rule = normalized
    return results


def rule_is_finite(rule):
    parts = {part.partition("=")[0] for part in normalize_rule(rule).split(";")}
    return bool(parts & {"COUNT", "UNTIL"})


def recurrence_exhausted(series, *, now):
    if not rule_is_finite(series.recurrence_rule):
        return False
    _normalized, rule, _anchor = parsed_rule(
        rule=series.recurrence_rule,
        local_date=series.dtstart_local_date,
        local_time=series.dtstart_local_time,
        timezone_name=series.recurrence_timezone,
    )
    return rule.after(now.astimezone(_timezone(series.recurrence_timezone)), inc=False) is None
