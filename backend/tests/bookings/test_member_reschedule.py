from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.services_reschedule import reschedule_booking
from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.payments.models import Payment
from tests.bookings.test_member_booking_api import setup, book, member

pytestmark = pytest.mark.django_db


def url(space, booking):
    return reverse('member-booking-reschedule', kwargs={'makerspace_slug': space.slug, 'public_token': booking.public_token})


def test_member_moves_same_reservation_and_charge_and_calendar_identity():
    space, room, user, client = setup('move-own-wp3', payment_amount='12.00')
    space.enabled_features = sorted(set(space.enabled_features) | {'charges.enabled', 'charges.bookings'})
    space.save(update_fields=['enabled_features', 'updated_at'])
    booking = book(room, user)
    payment_ids = list(Payment.objects.filter(subject_type='booking', subject_id=booking.pk).values_list('pk', flat=True))
    assert len(payment_ids) == 1
    before = booking.starts_at
    response = client.post(url(space, booking), {'starts_at': (before + timedelta(days=1)).isoformat(),
                                                'ends_at': (booking.ends_at + timedelta(days=1)).isoformat()}, format='json')
    assert response.status_code == 200 and response.data['public_token'] == str(booking.public_token)
    booking.refresh_from_db()
    assert booking.starts_at == before + timedelta(days=1) and booking.calendar_sequence == 1
    assert list(Payment.objects.filter(subject_type='booking', subject_id=booking.pk).values_list('pk', flat=True)) == payment_ids
    assert AuditLog.objects.get(action='booking.rescheduled').actor == user


def test_reschedule_respects_buffers_and_failure_keeps_old_window():
    space, room, user, _ = setup('move-buffer-wp3', buffer_after_minutes=30)
    mine = book(room, user)
    other, _ = member(space, 'move-other-wp3')
    occupied = book(room, other, starts_at=mine.starts_at + timedelta(days=1))
    with pytest.raises(BookingConflict):
        reschedule_booking(mine, actor=user, starts_at=occupied.ends_at + timedelta(minutes=15),
                           ends_at=occupied.ends_at + timedelta(hours=1, minutes=15))
    mine.refresh_from_db()
    assert mine.calendar_sequence == 0
    assert not AuditLog.objects.filter(action='booking.rescheduled').exists()


def test_cutoff_ownership_and_module_off_are_enforced(monkeypatch):
    from tests.module_helpers import disable_module
    space, room, user, client = setup('move-access-wp3', cancellation_cutoff_hours=24)
    mine = book(room, user)
    other, other_client = member(space, 'move-intruder-wp3')
    values = {'starts_at': (mine.starts_at + timedelta(days=1)).isoformat(), 'ends_at': (mine.ends_at + timedelta(days=1)).isoformat()}
    assert other_client.post(url(space, mine), values, format='json').status_code == 404
    with pytest.raises(BookingInvalidTransition):
        reschedule_booking(mine, actor=other, starts_at=mine.starts_at, ends_at=mine.ends_at)
    monkeypatch.setattr(timezone, 'now', lambda: mine.starts_at - timedelta(hours=24))
    assert client.post(url(space, mine), values, format='json').status_code == 409
    disable_module(space, 'bookings')
    assert client.post(url(space, mine), values, format='json').status_code == 400


def test_account_only_owner_can_reschedule_but_revoked_membership_denies_own_access():
    from apps.makerspaces.models import MakerspaceMembership
    from tests.return_helpers import make_user, authenticated_client
    space, room, _, _ = setup('move-account-only-wp3')
    user = make_user('move-account-only-owner-wp3', phone='123')
    mine = book(room, user)
    client = authenticated_client(user)
    values = {'starts_at': (mine.starts_at + timedelta(days=1)).isoformat(),
              'ends_at': (mine.ends_at + timedelta(days=1)).isoformat()}
    assert client.post(url(space, mine), values, format='json').status_code == 200
    MakerspaceMembership.objects.create(makerspace=space, user=user, status='revoked')
    assert client.post(url(space, mine), values, format='json').status_code == 404
    with pytest.raises(BookingInvalidTransition):
        reschedule_booking(mine, actor=user, starts_at=mine.starts_at, ends_at=mine.ends_at)


def test_reschedule_rechecks_opening_hours_and_preserves_pending_approval():
    from rest_framework.exceptions import ValidationError
    space, room, user, client = setup('move-hours-wp3')
    room.approval_mode = 'approve'
    room.save(update_fields=['approval_mode'])
    mine = book(room, user)
    old_start = mine.starts_at
    proposed = old_start + timedelta(days=1)
    # Closing the proposed local day must be checked against current policy,
    # even though the original reservation was valid when it was created.
    from apps.makerspaces.local_time import to_local
    local = to_local(space, proposed)
    space.opening_hours = {'exceptions': {local.date().isoformat(): []}}
    space.save(update_fields=['opening_hours', 'updated_at'])
    with pytest.raises(ValidationError):
        reschedule_booking(mine, actor=user, starts_at=proposed, ends_at=proposed + timedelta(hours=1))
    mine.refresh_from_db()
    assert mine.starts_at == old_start and mine.status == 'pending' and mine.calendar_sequence == 0
    space.opening_hours = {}
    space.save(update_fields=['opening_hours', 'updated_at'])
    result = client.post(url(space, mine), {'starts_at': proposed.isoformat(), 'ends_at': (proposed + timedelta(hours=1)).isoformat()}, format='json')
    assert result.status_code == 200 and result.data['status'] == 'pending'
