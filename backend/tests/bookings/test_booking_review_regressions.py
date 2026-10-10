"""Review regressions: bound calendar work and preserve public input contracts."""

from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from rest_framework import serializers

from apps.bookings import services
from apps.bookings.models import Booking
from tests.bookings.test_booking_schedule_policy import space, start
from tests.bookings.test_public_api import booking_url
from tests.member_submission import active_member_client

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('invalid', ['duration', 'advance'])
def test_invalid_booking_range_is_rejected_before_calendar_traversal(monkeypatch, invalid):
    room = space()
    begins = start() if invalid == 'duration' else datetime(9999, 1, 1, tzinfo=dt_timezone.utc)
    ends = datetime(9999, 12, 31, tzinfo=dt_timezone.utc) if invalid == 'duration' else begins + timedelta(hours=1)
    calls = []
    monkeypatch.setattr('apps.bookings.services_schedule.enforce_opening_hours',
                        lambda *args: calls.append(args))
    with pytest.raises(serializers.ValidationError) as error:
        services.create_booking(room, starts_at=begins, ends_at=ends,
                                name='Member', email='member@example.test', phone='123')
    assert ('ends_at' if invalid == 'duration' else 'starts_at') in error.value.detail
    assert calls == []
    assert not Booking.objects.exists()


@pytest.mark.parametrize('body', [[], ['invalid'], 'invalid'])
def test_public_booking_refuses_non_object_json(body):
    room = space(is_public=True)
    _, client = active_member_client(room.makerspace, 'public-body')
    response = client.post(booking_url(room.makerspace, room), body, format='json')
    assert response.status_code == 400
    assert not Booking.objects.exists()


def test_honeypot_keeps_its_noop_contract_without_dates():
    room = space(is_public=True)
    _, client = active_member_client(room.makerspace, 'public-honeypot')
    response = client.post(booking_url(room.makerspace, room), {'website': 'bot.example'}, format='json')
    assert response.status_code == 201
    assert not Booking.objects.exists()
