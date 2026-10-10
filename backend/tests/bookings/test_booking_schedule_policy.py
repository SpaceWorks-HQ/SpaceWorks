from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.bookings import services
from apps.bookings.exceptions import BookingConflict
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def space(**values):
    tenant = Makerspace.objects.create(name='Schedule', slug='schedule', timezone='UTC')
    return BookableSpace.objects.create(
        makerspace=tenant, name='Room', approval_mode='instant',
        booking_lead_time_minutes=0, **values,
    )


def start():
    return (timezone.now() + timedelta(days=5)).replace(hour=10, minute=0, second=0, microsecond=0)


def book(room, begins, duration=60):
    return services.create_booking(
        room, starts_at=begins, ends_at=begins + timedelta(minutes=duration),
        name='Member', email='member@example.test', phone='123',
    )


def hours(room, begins, intervals):
    room.makerspace.opening_hours = {
        'weekly': {}, 'exceptions': {begins.date().isoformat(): intervals},
    }
    room.makerspace.save(update_fields=['opening_hours'])


def test_buffers_refuse_overlap_and_allow_exact_half_open_boundary():
    room = space(buffer_before_minutes=10, buffer_after_minutes=20)
    begins = start()
    book(room, begins)
    with pytest.raises(BookingConflict):
        book(room, begins + timedelta(minutes=89))
    assert book(room, begins + timedelta(minutes=90)).status == Booking.Status.CONFIRMED
    with pytest.raises(BookingConflict):
        book(room, begins - timedelta(minutes=89))


def test_buffer_edit_cannot_introduce_overlap_between_existing_bookings():
    room = space()
    begins = start()
    book(room, begins)
    book(room, begins + timedelta(minutes=75))
    with pytest.raises(serializers.ValidationError):
        services.update_booking_rules(room, actor=None, buffer_after_minutes=16)
    room.refresh_from_db()
    assert room.buffer_after_minutes == 0
    assert services.update_booking_rules(room, actor=None, buffer_after_minutes=15).buffer_after_minutes == 15


def test_dated_closed_day_refuses_create_and_approval():
    room = space()
    begins = start()
    hours(room, begins, [])
    with pytest.raises(serializers.ValidationError):
        book(room, begins)
    room.approval_mode = 'approve'
    room.save(update_fields=['approval_mode'])
    hours(room, begins, [{'start': '09:00', 'end': '17:00'}])
    pending = book(room, begins)
    hours(room, begins, [])
    with pytest.raises(serializers.ValidationError):
        services.approve_booking(pending, actor=None)
    pending.refresh_from_db()
    assert pending.status == Booking.Status.PENDING


def test_opening_interval_boundaries_include_cleanup_and_lunch_gaps():
    room = space(buffer_before_minutes=15, buffer_after_minutes=15)
    begins = start()
    hours(room, begins, [{'start': '10:00', 'end': '12:00'}, {'start': '13:00', 'end': '17:00'}])
    with pytest.raises(serializers.ValidationError):
        book(room, begins)
    assert book(room, begins + timedelta(minutes=15), 90).status == Booking.Status.CONFIRMED
    with pytest.raises(serializers.ValidationError):
        book(room, begins + timedelta(hours=1, minutes=45))


def test_empty_hours_allow_overnight_booking():
    room = space()
    assert book(room, start().replace(hour=23), 120).status == Booking.Status.CONFIRMED


def test_dst_interval_uses_makerspace_local_wall_clock(monkeypatch):
    room = space()
    room.makerspace.timezone = 'America/New_York'
    room.makerspace.opening_hours = {
        'weekly': {}, 'exceptions': {'2030-03-10': [{'start': '01:00', 'end': '04:00'}]},
    }
    room.makerspace.save(update_fields=['timezone', 'opening_hours'])
    begins = datetime(2030, 3, 10, 6, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, 'now', lambda: begins - timedelta(days=1))
    # The spring-forward day opens for two elapsed hours despite three wall hours.
    assert book(room, begins, 120).status == Booking.Status.CONFIRMED
    with pytest.raises(serializers.ValidationError):
        book(room, begins, 121)


@pytest.mark.parametrize('operation', ['create', 'approve'])
@pytest.mark.django_db(transaction=True)
def test_buffer_overlap_serializes_concurrent_reservations(operation, monkeypatch):
    room = space(buffer_after_minutes=30)
    begins = start()
    monkeypatch.setattr('apps.bookings.notifications.notify_booking_status', lambda *args, **kwargs: None)
    starts = [begins, begins + timedelta(minutes=75)]
    rows = []
    if operation == 'approve':
        room.approval_mode = 'approve'
        room.save(update_fields=['approval_mode'])
        rows = [book(room, value) for value in starts]
    barrier = Barrier(2)

    def reserve(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            if operation == 'approve':
                services.approve_booking(Booking.objects.get(pk=rows[index].pk), actor=None)
            else:
                book(BookableSpace.objects.get(pk=room.pk), starts[index])
            return 'confirmed'
        except BookingConflict:
            return 'conflict'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(reserve, index) for index in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == ['confirmed', 'conflict']
    assert Booking.objects.filter(space=room, status=Booking.Status.CONFIRMED).count() == 1


def test_public_busy_windows_include_buffers_without_exposing_private_policy():
    room = space(buffer_before_minutes=15, buffer_after_minutes=30,
                 is_public=True, show_public_availability=True)
    begins = start()
    book(room, begins)
    response = APIClient().get(reverse('public-space-availability', kwargs={
        'makerspace_slug': room.makerspace.slug, 'public_token': room.public_token,
    }), {'starts_at': begins.isoformat(), 'ends_at': (begins + timedelta(days=1)).isoformat()})
    assert response.status_code == 200
    busy = response.data['availability'][0]
    assert busy['starts_at'] == (begins - timedelta(minutes=15)).isoformat().replace('+00:00', 'Z')
    assert busy['ends_at'] == (begins + timedelta(minutes=90)).isoformat().replace('+00:00', 'Z')
    assert busy['booker_name'] is None
    assert 'buffer_before_minutes' not in response.data
    assert response.data['timezone'] == 'UTC'
    assert response.data['opening_intervals']


@pytest.mark.parametrize('field', ['buffer_before_minutes', 'buffer_after_minutes', 'cancellation_cutoff_hours'])
def test_rule_updates_validate_policy_bounds_and_audit(field):
    from apps.audit.models import AuditLog

    room = space()
    with pytest.raises(serializers.ValidationError):
        services.update_booking_rules(room, actor=None, **{field: -1})
    updated = services.update_booking_rules(room, actor=None, **{field: 2})
    assert getattr(updated, field) == 2
    assert AuditLog.objects.get(action='booking.space_rules_updated').meta['changed_fields'] == [field]
