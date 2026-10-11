from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.bookings import services
from apps.bookings.exceptions import BookingInvalidTransition
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole, MakerspaceWaiver
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


def setup(slug='my-bookings', **room_values):
    tenant = Makerspace.objects.create(name=slug, slug=slug)
    room = BookableSpace.objects.create(
        makerspace=tenant, name='Room', approval_mode='instant', **room_values,
    )
    user, client = member(tenant, f'{slug}-member')
    return tenant, room, user, client


def member(tenant, username):
    user = User.objects.create_user(username=username, email=f'{username}@example.test', phone='123')
    MakerspaceMembership.objects.create(
        makerspace=tenant, user=user, role='custom',
        assigned_role=MakerspaceRole.objects.get(makerspace=tenant, slug='member'),
    )
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def book(room, user, *, starts_at=None):
    begins = starts_at or timezone.now() + timedelta(days=2)
    return services.create_booking(room, member=user, actor=user,
                                   starts_at=begins, ends_at=begins + timedelta(hours=1))


def list_url(tenant):
    return reverse('member-booking-list', kwargs={'makerspace_slug': tenant.slug})


def cancel_url(tenant, booking):
    return reverse('member-booking-cancel', kwargs={
        'makerspace_slug': tenant.slug, 'public_token': booking.public_token,
    })


def test_own_upcoming_and_past_history_never_matches_shared_contact_fields():
    tenant, room, user, client = setup()
    mine = book(room, user)
    other, _ = member(tenant, 'another')
    other_booking = book(room, other, starts_at=mine.starts_at + timedelta(hours=2))
    # Accounts have unique verified emails; historical booking contacts may still match.
    other_booking.email = user.email
    other_booking.phone = user.phone
    other_booking.save(update_fields=['email', 'phone'])
    past = Booking.objects.create(space=room, member=user, name='Mine', email=user.email, phone=user.phone,
                                  starts_at=timezone.now() - timedelta(days=2),
                                  ends_at=timezone.now() - timedelta(days=1), status='completed')
    result = client.get(list_url(tenant))
    assert result.status_code == 200 and result.data['count'] == 1
    row = result.data['results'][0]
    assert row['public_token'] == str(mine.public_token)
    assert row['can_cancel'] is True
    assert not {'email', 'phone', 'note', 'member', 'custom_answers'} & set(row)
    history = client.get(list_url(tenant), {'period': 'past'})
    assert history.status_code == 200 and history.data['count'] == 1
    assert history.data['results'][0]['public_token'] == str(past.public_token)
    assert history.data['results'][0]['can_cancel'] is False
    assert client.get(list_url(tenant), {'period': 'invalid'}).status_code == 400


@pytest.mark.parametrize('approval_mode', ['instant', 'approve'])
def test_member_cancel_pending_or_confirmed_is_audited_and_does_not_need_presence_or_new_waiver(approval_mode):
    tenant, room, user, client = setup()
    room.approval_mode = approval_mode
    room.save(update_fields=['approval_mode'])
    booking = book(room, user)
    MakerspaceWaiver.objects.create(makerspace=tenant, body='New waiver', version='v2', is_active=True)
    response = client.post(cancel_url(tenant, booking), {}, format='json')
    assert response.status_code == 200 and response.data['status'] == 'cancelled'
    booking.refresh_from_db()
    assert booking.status == Booking.Status.CANCELLED
    assert AuditLog.objects.get(action='booking.cancelled').actor == user
    assert client.post(cancel_url(tenant, booking), {}, format='json').status_code == 409


@pytest.mark.parametrize('seconds_before', [1, 0, -1])
def test_cutoff_is_enforced_on_current_locked_policy(monkeypatch, seconds_before):
    tenant, room, user, client = setup()
    booking = book(room, user)
    # Policy changes after creation must take effect; no caller snapshot is authoritative.
    room.cancellation_cutoff_hours = 24
    room.save(update_fields=['cancellation_cutoff_hours'])
    cutoff = booking.starts_at - timedelta(hours=24)
    monkeypatch.setattr(timezone, 'now', lambda: cutoff - timedelta(seconds=seconds_before))
    response = client.post(cancel_url(tenant, booking), {}, format='json')
    assert response.status_code == (200 if seconds_before > 0 else 409)
    booking.refresh_from_db()
    assert booking.status == ('cancelled' if seconds_before > 0 else 'confirmed')


def test_service_refuses_another_actor_and_http_refuses_cross_tenant_and_unowned_rows():
    tenant, room, user, client = setup()
    booking = book(room, user)
    outsider, other_client = member(tenant, 'other-owner')
    with pytest.raises(BookingInvalidTransition):
        services.cancel_booking(booking, actor=outsider, member_cancel=True)
    assert other_client.post(cancel_url(tenant, booking), {}, format='json').status_code == 404
    other_tenant, other_room, _, _ = setup('other-space')
    assert client.post(cancel_url(other_tenant, booking), {}, format='json').status_code == 404
    # Membership in both tenants still cannot cancel a row through the wrong tenant.
    MakerspaceMembership.objects.create(makerspace=other_tenant, user=user)
    assert client.post(cancel_url(other_tenant, booking), {}, format='json').status_code == 404
    assert client.get(list_url(other_tenant)).data['count'] == 0
    assert APIClient().get(list_url(tenant)).status_code == 401
    assert APIClient().post(cancel_url(tenant, booking), {}, format='json').status_code == 401


def test_module_off_is_400_for_list_and_cancel_and_body_refuses_extra_fields():
    tenant, room, user, client = setup()
    booking = book(room, user)
    assert client.post(cancel_url(tenant, booking), {'member_id': user.pk}, format='json').status_code == 400
    tenant.enabled_modules.remove('bookings')
    tenant.save(update_fields=['enabled_modules'])
    assert client.get(list_url(tenant)).status_code == 400
    assert client.post(cancel_url(tenant, booking), {}, format='json').status_code == 400


def test_cancellation_voids_pending_charge_once_and_keeps_settled_money():
    tenant, room, user, client = setup(payment_amount=Decimal('12.50'))
    tenant.enabled_features = ['charges.enabled', 'charges.bookings']
    tenant.save(update_fields=['enabled_features'])
    booking = book(room, user)
    payment = Payment.objects.get(subject_type='booking', subject_id=booking.pk)
    assert client.post(cancel_url(tenant, booking), {}, format='json').status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.CANCELED
    assert AuditLog.objects.get(action='payment.canceled').actor == user
    second = book(room, user, starts_at=booking.starts_at + timedelta(hours=2))
    # Import/legacy paid row: cancellation must preserve the receipt.
    paid = Payment.objects.get(subject_type='booking', subject_id=second.pk)
    paid.status = Payment.Status.PAID_ONLINE
    paid.save(update_fields=['status', 'updated_at'])
    assert client.post(cancel_url(tenant, second), {}, format='json').status_code == 200
    paid.refresh_from_db()
    assert paid.status == Payment.Status.PAID_ONLINE


def test_my_bookings_is_paginated_and_documents_all_routes():
    tenant, room, user, client = setup()
    begins = timezone.now() + timedelta(days=2)
    for index in range(25):
        book(room, user, starts_at=begins + timedelta(hours=index * 2))
    first = client.get(list_url(tenant))
    assert first.status_code == 200 and first.data['count'] == 25
    assert len(first.data['results']) == 24 and first.data['next']
    second = client.get(list_url(tenant), {'page': 2})
    assert len(second.data['results']) == 1 and second.data['previous']
    paths = SchemaGenerator().get_schema(public=True)['paths']
    get = paths['/api/v1/public/{makerspace_slug}/my-bookings/']['get']
    post = paths['/api/v1/public/{makerspace_slug}/my-bookings/{public_token}/cancel/']['post']
    assert {'200', '400', '401', '403', '404', '429'} <= set(get['responses'])
    assert {'200', '400', '401', '403', '404', '409', '429'} <= set(post['responses'])
    assert get['security'] and post['security'] and post['requestBody']
