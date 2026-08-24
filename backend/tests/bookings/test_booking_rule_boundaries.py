from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.bookings import services_bookings
from apps.bookings.exceptions import BookingConflict
from apps.bookings.models import BookableSpace, Booking
from tests.bookings.test_booking_rules import create_booking, make_space


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ('starts_delta', 'duration', 'field'),
    (
        (timedelta(hours=2), timedelta(minutes=29), 'ends_at'),
        (timedelta(hours=2), timedelta(minutes=481), 'ends_at'),
        (timedelta(minutes=59), timedelta(minutes=60), 'starts_at'),
        (timedelta(days=30, seconds=1), timedelta(minutes=60), 'starts_at'),
    ),
)
def test_create_booking_rejects_rule_failures_without_rows_or_audit(
    monkeypatch, starts_delta, duration, field
):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    space = make_space()
    before = AuditLog.objects.count()
    starts_at = now + starts_delta

    with pytest.raises(serializers.ValidationError) as caught:
        create_booking(space, starts_at, starts_at + duration)

    assert set(caught.value.detail) == {field}
    assert not Booking.objects.filter(space=space).exists()
    assert AuditLog.objects.count() == before


@pytest.mark.parametrize(
    ('starts_delta', 'duration'),
    (
        (timedelta(hours=2), timedelta(minutes=30)),
        (timedelta(hours=2), timedelta(minutes=480)),
        (timedelta(minutes=60), timedelta(minutes=60)),
        (timedelta(days=30), timedelta(minutes=60)),
    ),
)
def test_create_booking_allows_exact_rule_boundaries(
    monkeypatch, starts_delta, duration
):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    space = make_space()
    starts_at = now + starts_delta

    booking = create_booking(space, starts_at, starts_at + duration)

    assert booking.pk is not None


def test_valid_booking_still_creates_and_overlap_still_conflicts(monkeypatch):
    now = datetime(2030, 1, 1, tzinfo=datetime_timezone.utc)
    monkeypatch.setattr(services_bookings.timezone, 'now', lambda: now)
    # Pending requests may overlap; this test protects instant-confirmed conflicts.
    space = make_space(approval_mode=BookableSpace.ApprovalMode.INSTANT)
    starts_at = now + timedelta(hours=2)
    first = create_booking(space, starts_at, starts_at + timedelta(hours=1))
    before = AuditLog.objects.count()

    with pytest.raises(BookingConflict):
        create_booking(
            space,
            starts_at + timedelta(minutes=30),
            starts_at + timedelta(minutes=90),
        )

    assert first.status == Booking.Status.CONFIRMED
    assert Booking.objects.filter(space=space).count() == 1
    assert AuditLog.objects.count() == before
