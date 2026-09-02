from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


@dataclass(frozen=True)
class CheckInWindow:
    opens_at: object
    closes_at: object
    sync_deadline: object


def window_for(event):
    return CheckInWindow(
        opens_at=event.starts_at - timedelta(
            hours=settings.EVENT_CHECKIN_WINDOW_BEFORE_HOURS
        ),
        closes_at=event.ends_at + timedelta(
            hours=settings.EVENT_CHECKIN_WINDOW_AFTER_HOURS
        ),
        sync_deadline=event.ends_at
        + timedelta(
            hours=(
                settings.EVENT_CHECKIN_WINDOW_AFTER_HOURS
                + settings.EVENT_CHECKIN_SYNC_GRACE_HOURS
            )
        ),
    )


def roster_expiry(event, *, now=None):
    now = now or timezone.now()
    window = window_for(event)
    return min(
        now + timedelta(hours=settings.EVENT_CHECKIN_ROSTER_LIFETIME_HOURS),
        window.sync_deadline,
    )


def download_is_open(event, *, now=None):
    now = now or timezone.now()
    window = window_for(event)
    return window.opens_at <= now <= window.closes_at


def reported_time_is_valid(reported_at, lease, *, received_at=None):
    received_at = received_at or timezone.now()
    opens_at = _datetime(lease["scan_opens_at"])
    closes_at = _datetime(lease["scan_closes_at"])
    expires_at = _datetime(lease["expires_at"])
    future_limit = received_at + timedelta(
        seconds=settings.EVENT_CHECKIN_CLOCK_SKEW_SECONDS
    )
    return (
        opens_at <= reported_at <= closes_at
        and reported_at <= expires_at
        and reported_at <= future_limit
    )


def sync_is_open(lease, *, now=None):
    return (now or timezone.now()) <= _datetime(lease["sync_deadline"])


def _datetime(value):
    if hasattr(value, "tzinfo"):
        return value
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else timezone.make_aware(parsed)
