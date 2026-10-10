"""Staff on-behalf bookings preserve tenant, membership, waiver and training boundaries."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.audit.models import AuditLog
from apps.bookings.models import Booking
from apps.makerspaces.waiver_services import accept_waiver, publish_waiver
from tests.machines.certification_helpers import (
    _bookable, _certification, _machine_type, _manager, _member, _space,
)
from tests.module_helpers import disable_module


pytestmark = pytest.mark.django_db


def setup_booking(slug='staff-booking', *, certified=False):
    makerspace = _space(slug, certifications=certified)
    actor, _ = _manager(makerspace, slug + '-desk', actions=(Action.MANAGE_BOOKINGS,))
    member, membership = _member(makerspace, slug + '-member')
    space = _bookable(makerspace)
    client = APIClient()
    client.force_authenticate(actor)
    return makerspace, actor, member, membership, space, client


def payload(member, **values):
    starts_at = timezone.now() + timedelta(days=1)
    return {
        'member_id': member.pk, 'starts_at': starts_at.isoformat(),
        'ends_at': (starts_at + timedelta(hours=1)).isoformat(), **values,
    }


def create(client, space, values):
    return client.post(reverse('admin-space-booking-list', kwargs={'pk': space.pk}), values, format='json')


def test_staff_books_without_presence_and_snapshots_member_with_actor_audit():
    makerspace, actor, member, _, space, client = setup_booking()
    response = create(client, space, payload(member, note='Front desk reservation'))
    assert response.status_code == 201
    row = Booking.objects.get(pk=response.data['id'])
    assert row.member_id == member.pk
    assert (row.name, row.email, row.phone) == (member.username, member.email, member.phone)
    assert row.note == 'Front desk reservation'
    assert AuditLog.objects.filter(makerspace=makerspace, actor=actor, action='booking.created').exists()


def test_staff_booking_refuses_other_tenant_space_and_member():
    _, _, member, _, space, client = setup_booking()
    other, _, outsider, _, other_space, _ = setup_booking('other-staff-booking')
    assert create(client, other_space, payload(member)).status_code == 404
    assert create(client, space, payload(outsider)).status_code == 404
    assert not Booking.objects.exists()


@pytest.mark.parametrize('status', ['pending', 'suspended', 'revoked'])
def test_staff_booking_refuses_inactive_membership(status):
    _, _, member, membership, space, client = setup_booking()
    membership.status = status
    membership.save(update_fields=['status'])
    assert create(client, space, payload(member)).status_code == 404
    assert not Booking.objects.exists()


@pytest.mark.parametrize('access_status', [User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED])
def test_staff_booking_refuses_restricted_account(access_status):
    _, _, member, _, space, client = setup_booking()
    member.access_status = access_status
    member.save(update_fields=['access_status'])
    assert create(client, space, payload(member)).status_code == 404


def test_staff_booking_requires_current_waiver():
    makerspace, actor, member, membership, space, client = setup_booking()
    publish_waiver(actor, makerspace, 'Terms', 'v1')
    response = create(client, space, payload(member))
    assert response.status_code == 403
    assert response.data['code'] == 'waiver_acceptance_required'
    accept_waiver(membership)
    assert create(client, space, payload(member)).status_code == 201


def test_staff_booking_override_needs_machine_type_authority_and_is_audited():
    makerspace, _, member, _, space, client = setup_booking(certified=True)
    machine_type = _machine_type(makerspace)
    _certification(makerspace, machine_type)
    space.machine_type = machine_type
    space.save(update_fields=['machine_type'])
    values = payload(member, certification_override_reason='Observed prior training')
    assert create(client, space, values).status_code == 403
    assert not AuditLog.objects.filter(action='certification.override').exists()
    manager, _ = _manager(
        makerspace, 'scoped-booking-manager', machine_type=machine_type,
        actions=(Action.MANAGE_MACHINES, Action.MANAGE_BOOKINGS),
    )
    client.force_authenticate(manager)
    assert create(client, space, payload(member)).status_code == 403
    assert create(client, space, values).status_code == 201
    assert AuditLog.objects.filter(actor=manager, action='certification.override', makerspace=makerspace).exists()


def test_member_cannot_use_staff_booking_and_module_off_returns_400():
    makerspace, actor, member, _, space, client = setup_booking()
    client.force_authenticate(member)
    assert create(client, space, payload(member)).status_code == 403
    client.force_authenticate(actor)
    disable_module(makerspace, 'bookings')
    assert create(client, space, payload(member)).status_code == 400


def test_staff_member_picker_is_scoped_paginated_and_excludes_inactive_accounts():
    makerspace, _, member, _, space, client = setup_booking()
    _, _, outsider, _, _, _ = setup_booking('picker-outsider')
    url = reverse('admin-space-booking-eligible-members', kwargs={'pk': space.pk})
    response = client.get(url)
    assert response.status_code == 200
    assert {'count', 'next', 'previous', 'results'} <= response.data.keys()
    ids = [row['member_id'] for row in response.data['results']]
    assert member.pk in ids and outsider.pk not in ids
    member.is_active = False
    member.save(update_fields=['is_active'])
    assert member.pk not in [row['member_id'] for row in client.get(url).data['results']]
    disable_module(makerspace, 'bookings')
    assert client.get(url).status_code == 400


def test_staff_booking_input_cannot_invent_status_or_override_flags():
    _, _, member, _, space, client = setup_booking()
    assert create(client, space, payload(member, status='confirmed')).status_code == 400
    assert create(client, space, []).status_code == 400
    assert create(client, space, payload(member, member_id=2**64)).status_code == 400
    assert not Booking.objects.exists()


def test_staff_booking_requires_explicit_timezone_offset():
    _, _, member, _, space, client = setup_booking()
    values = payload(member)
    values['starts_at'] = (timezone.now() + timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert create(client, space, values).status_code == 400
    assert not Booking.objects.exists()


def test_staff_booking_routes_have_schema_and_machine_editor_rejects_other_tenant_type():
    from drf_spectacular.generators import SchemaGenerator

    makerspace, _, _, _, space, client = setup_booking()
    machine_type = _machine_type(makerspace)
    url = reverse('admin-bookable-space-detail', kwargs={'pk': space.pk})
    response = client.patch(url, {'machine_type': machine_type.pk}, format='json')
    assert response.status_code == 200 and response.data['machine_type'] == machine_type.pk
    other = _space('foreign-booking-type')
    foreign_type = _machine_type(other)
    assert client.patch(url, {'machine_type': foreign_type.pk}, format='json').status_code == 400
    schema = SchemaGenerator().get_schema(public=True)
    create_schema = schema['paths']['/api/v1/admin/spaces/{id}/bookings/']['post']
    assert {'201', '400', '401', '403', '404', '409'} <= create_schema['responses'].keys()
    assert create_schema['requestBody']['content']['application/json']['schema']['$ref'].endswith('/StaffBookingInput')
    choices = schema['paths']['/api/v1/admin/spaces/{id}/eligible-members/']['get']
    assert {'200', '400', '401', '403', '404'} <= choices['responses'].keys()
