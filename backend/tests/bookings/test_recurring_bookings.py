from datetime import datetime, timedelta, timezone as utc

import pytest

from apps.bookings.models import Booking
from apps.bookings.services_recurrence import create_recurring_bookings
from apps.bookings.services_bookings import create_booking
from apps.audit.models import AuditLog
from rest_framework.exceptions import ValidationError
from tests.bookings.test_member_booking_api import setup
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db


def world(slug):
    space, room, user, _ = setup(slug, max_booking_advance_days=365)
    space.enabled_features = sorted(set(space.enabled_features) | {'bookings.recurring'})
    space.save(update_fields=['enabled_features', 'updated_at'])
    return space, room, user, make_member(slug + '-staff', space)


def test_occurrence_conflicts_are_explicit_and_only_successful_rows_are_audited():
    space, room, user, staff = world('repeat-wp3')
    space.enabled_features = sorted(set(space.enabled_features) | {'charges.enabled', 'charges.bookings'})
    space.save(update_fields=['enabled_features', 'updated_at'])
    room.payment_amount = '12.00'
    room.save(update_fields=['payment_amount'])
    from django.utils import timezone
    first = timezone.now() + timedelta(days=3)
    create_booking(room, starts_at=first + timedelta(weeks=1), ends_at=first + timedelta(weeks=1, hours=1), member=user, actor=staff)
    result = create_recurring_bookings(room, actor=staff, member=user, starts_at=first,
                                      ends_at=first + timedelta(hours=1), count=3)
    assert [row['status'] for row in result] == ['confirmed', 'conflict', 'confirmed']
    assert result[1]['booking_id'] is None and result[1]['detail']
    assert Booking.objects.filter(space=room).count() == 3
    assert AuditLog.objects.filter(action='booking.created', makerspace=space).count() == 3
    from apps.payments.models import Payment
    debts = Payment.objects.filter(makerspace=space, subject_type='booking')
    assert debts.count() == 3 and all(debt.amount == 12 for debt in debts)
    assert set(debts.values_list('subject_id', flat=True)) == set(Booking.objects.filter(space=room).values_list('pk', flat=True))


def test_weekly_recurrence_preserves_local_hour_across_dst(monkeypatch):
    from django.utils import timezone
    from apps.makerspaces.local_time import to_local
    space, room, user, staff = world('repeat-dst-wp3')
    space.timezone = 'America/New_York'
    space.save(update_fields=['timezone', 'updated_at'])
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 10, 20, tzinfo=utc.utc))
    first = datetime(2026, 10, 27, 22, tzinfo=utc.utc)  # 18:00 local before fall-back.
    result = create_recurring_bookings(room, actor=staff, member=user, starts_at=first,
                                      ends_at=first + timedelta(hours=1), count=3)
    assert all(to_local(space, row['starts_at']).hour == 18 for row in result)
    assert result[1]['starts_at'].hour == 23


def test_bounds_and_disabled_feature_refuse_before_creating_any_occurrence():
    from django.utils import timezone
    space, room, user, staff = world('repeat-bounds-wp3')
    first = timezone.now() + timedelta(days=2)
    with pytest.raises(ValidationError):
        create_recurring_bookings(room, actor=staff, member=user, starts_at=first, ends_at=first + timedelta(hours=1), count=53)
    space.enabled_features = [key for key in space.enabled_features if key != 'bookings.recurring']
    space.save(update_fields=['enabled_features', 'updated_at'])
    with pytest.raises(ValidationError):
        create_recurring_bookings(room, actor=staff, member=user, starts_at=first, ends_at=first + timedelta(hours=1), count=3)
    assert not Booking.objects.filter(space=room).exists()


def test_recurring_route_resolves_its_space_for_custom_domain_authority():
    from django.test import RequestFactory
    from django.urls import resolve, reverse
    from apps.makerspaces.origin_scope_routes import request_route_targets
    space, room, _, _ = world('repeat-origin-wp3')
    path = reverse('admin-recurring-bookings', kwargs={'pk': room.pk})
    request = RequestFactory().post(path, content_type='application/json', data='{}')
    request.resolver_match = resolve(path)
    _, targets, invalid, recognized = request_route_targets(request)
    assert recognized and not invalid and targets == {space.pk}
