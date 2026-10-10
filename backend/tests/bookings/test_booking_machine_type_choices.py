"""B17 choices use booking authority and never widen access to the Machines console."""

import pytest
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator

from tests.bookings.test_staff_booking_access import setup_booking
from tests.machines.certification_helpers import _machine_type, _space
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def test_booking_only_staff_can_choose_own_and_builtin_types_without_machine_access():
    from apps.accounts import rbac
    from apps.machines.models import MachineType

    makerspace, actor, member, membership, space, client = setup_booking('type-choices')
    own = _machine_type(makerspace)
    foreign = _machine_type(_space('foreign-type-choices'))
    url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': makerspace.pk})
    assert not rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace.pk)
    response = client.get(url)
    assert response.status_code == 200
    choices = response.data['results']
    assert own.pk in {item['id'] for item in choices}
    assert foreign.pk not in {item['id'] for item in choices}
    assert all(set(item) == {'id', 'name'} for item in choices)
    assert response.data['count'] == MachineType.objects.filter(makerspace__isnull=True).count() + 1
    # Linking remains the existing audited MANAGE_BOOKINGS operation.
    detail = reverse('admin-bookable-space-detail', kwargs={'pk': space.pk})
    assert client.patch(detail, {'machine_type': own.pk}, format='json').status_code == 200


def test_type_choices_refuse_members_and_foreign_tenants():
    mine, actor, member, membership, space, client = setup_booking('type-scope')
    other = _space('type-other')
    foreign_url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': other.pk})
    assert client.get(foreign_url).status_code == 404
    client.force_authenticate(member)
    url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': mine.pk})
    assert client.get(url).status_code == 403


def test_org_booking_authority_can_choose_types_from_its_verified_domain():
    from apps.accounts import rbac
    from tests.organizations.test_org_console_access import client_for, org_actor

    actor, makerspace, organization, membership = org_actor('org-booking-types', rbac.Action.MANAGE_BOOKINGS)
    machine_type = _machine_type(makerspace)
    assert not actor.makerspace_memberships.exists()
    url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': makerspace.pk})
    response = client_for(actor).get(url, HTTP_ORIGIN=f'https://{makerspace.frontend_domain}')
    assert response.status_code == 200
    assert machine_type.pk in {item['id'] for item in response.data['results']}


@pytest.mark.parametrize('module', ['bookings', 'machines'])
def test_type_choices_module_off_returns_400(module):
    makerspace, actor, member, membership, space, client = setup_booking('type-off')
    disable_module(makerspace, module)
    url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': makerspace.pk})
    assert client.get(url).status_code == 400


def test_type_choices_are_paginated_and_have_openapi_errors():
    makerspace, actor, member, membership, space, client = setup_booking('type-pages')
    from apps.machines.models import MachineType

    for number in range(25):
        MachineType.objects.create(makerspace=makerspace, name=f'Custom {number}', slug=f'custom-{number}')
    url = reverse('admin-booking-machine-types', kwargs={'makerspace_id': makerspace.pk})
    first = client.get(url)
    assert first.status_code == 200 and len(first.data['results']) == 24
    assert first.data['next']
    second = client.get(url, {'page': 2})
    assert second.status_code == 200 and second.data['previous']
    assert not {item['id'] for item in first.data['results']} & {item['id'] for item in second.data['results']}
    operation = SchemaGenerator().get_schema(public=True)['paths'][
        '/api/v1/admin/makerspaces/{makerspace_id}/booking-machine-types/'
    ]['get']
    assert {'200', '400', '401', '403', '404'} <= operation['responses'].keys()
    assert operation['security']
