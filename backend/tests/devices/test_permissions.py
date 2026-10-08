"""MANAGE_DEVICES authority: defaults, custom grants, tenant scoping and module gating."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.devices.helpers import create_device, device_space, staff_client
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def test_only_space_manager_holds_manage_devices_by_default():
    space = device_space("perm-defaults")
    manager = make_member("perm-sm", space)
    inventory = make_member("perm-im", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    machines = make_member("perm-mm", space, membership_role=MakerspaceMembership.Role.MACHINE_MANAGER)
    assert rbac.can(manager, rbac.Action.MANAGE_DEVICES, space.pk)
    assert not rbac.can(inventory, rbac.Action.MANAGE_DEVICES, space.pk)
    assert not rbac.can(machines, rbac.Action.MANAGE_DEVICES, space.pk)
    assert rbac.Action.MANAGE_DEVICES not in rbac.ORGANIZATION_GRANTABLE_ACTIONS
    assert rbac.Action.MANAGE_DEVICES in rbac.ROLE_GRANTABLE_ACTIONS
    seeded = MakerspaceRole.objects.get(makerspace=space, legacy_role="space_manager")
    assert "manage_devices" in seeded.granted_actions


def test_a_custom_role_can_be_granted_the_action():
    space = device_space("perm-custom")
    role = MakerspaceRole.objects.create(
        makerspace=space, name="Device desk", slug="device-desk", granted_actions=["manage_devices"],
    )
    user = make_member("perm-custom-user", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    MakerspaceMembership.objects.filter(user=user, makerspace=space).update(assigned_role=role)
    response = _client(user).get(reverse("devices:admin-device-list", args=[space.pk]))
    assert response.status_code == 200 and response.data["count"] == 0


def test_inventory_manager_is_refused_and_restricted_staff_are_refused():
    space = device_space("perm-refused")
    inventory = make_member("perm-ref-im", space, membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER)
    url = reverse("devices:admin-device-list", args=[space.pk])
    assert _client(inventory).get(url).status_code == 403
    manager = make_member("perm-ref-sm", space)
    manager.access_status = "restricted"
    manager.save(update_fields=["access_status"])
    assert _client(manager).get(url).status_code == 403


def test_list_and_detail_are_tenant_scoped():
    space_a, space_b = device_space("perm-a"), device_space("perm-b")
    _ma, client_a = staff_client(space_a, "perm-a-mgr")
    _mb, client_b = staff_client(space_b, "perm-b-mgr")
    created = create_device(client_a, space_a)
    listing = client_b.get(reverse("devices:admin-device-list", args=[space_b.pk]))
    assert listing.status_code == 200 and listing.data["count"] == 0
    assert set(listing.data) == {"count", "next", "previous", "results"}
    detail = reverse("devices:admin-device-detail", args=[created["device"]["id"]])
    assert client_b.get(detail).status_code == 404
    assert client_b.patch(detail, {"name": "x"}, format="json").status_code == 404
    assert client_b.post(reverse("devices:admin-device-revoke", args=[created["device"]["id"]])).status_code == 404
    assert client_b.get(reverse("devices:admin-device-list", args=[space_a.pk])).status_code == 403


def test_module_off_answers_400_naming_the_module():
    space = make_space("perm-moduleoff")
    _manager, client = staff_client(space, "perm-moduleoff-mgr")
    space.enabled_modules = [key for key in space.enabled_modules if key != "devices"]
    space.save(update_fields=["enabled_modules"])
    response = client.get(reverse("devices:admin-device-list", args=[space.pk]))
    assert response.status_code == 400 and "devices" in str(response.data)
