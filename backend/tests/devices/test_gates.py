"""Module, liveness, source-gate and origin-scope gates on staff and enrollment routes."""

import pytest
from django.test import RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.devices.models import Device, DeviceEnrollment, DeviceEvent
from apps.ed25519 import encode_key, generate_keypair
from apps.makerspaces.models import Makerspace
from apps.makerspaces.origin_scope_routes import request_route_targets
from tests.devices.helpers import create_device, device_space, staff_client
from tests.module_helpers import disable_module
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db


def _challenge(grant, client=None):
    _private, raw = generate_keypair()
    return (client or APIClient()).post(
        reverse("devices:device-enrollment-challenge", args=[grant["enrollment_id"]]),
        {"token": grant["token"], "public_key": encode_key(raw)}, format="json",
    )


def test_module_off_refuses_create_and_enrollment_without_writing():
    space = device_space("gate-module")
    _manager, client = staff_client(space, "gate-module-mgr")
    created = create_device(client, space)
    disable_module(space, "devices")
    response = client.post(
        reverse("devices:admin-device-list", args=[space.pk]),
        {"kind": "printer", "name": "Late"}, format="json",
    )
    assert response.status_code == 400 and "devices" in str(response.data)
    assert Device.objects.filter(makerspace=space).count() == 1
    challenge = _challenge(created["enrollment"])
    assert challenge.status_code == 400
    enrollment = DeviceEnrollment.objects.get(pk=created["enrollment"]["enrollment_id"])
    assert enrollment.challenge_digest == ""


@pytest.mark.parametrize("state", ["archived", "importing", "aborted"])
def test_unservable_tenants_refuse_both_enrollment_routes(state):
    space = device_space(f"gate-{state}")
    _manager, client = staff_client(space, f"gate-{state}-mgr")
    created = create_device(client, space)
    if state == "archived":
        Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    else:
        Makerspace.objects.filter(pk=space.pk).update(lifecycle_state=state)
    assert _challenge(created["enrollment"]).status_code in (400, 403)
    complete = APIClient().post(
        reverse("devices:device-enrollment-complete", args=[created["enrollment"]["enrollment_id"]]),
        {"token": created["enrollment"]["token"], "public_key": encode_key(generate_keypair()[1]),
         "challenge": "A" * 43, "signature": encode_key(b"\0" * 64)}, format="json",
    )
    assert complete.status_code in (400, 403)
    assert Device.objects.get(pk=created["device"]["id"]).status == "pending"


def test_closed_source_gate_refuses_staff_and_enrollment_writes():
    space = device_space("gate-source")
    _manager, client = staff_client(space, "gate-source-mgr")
    created = create_device(client, space)
    close_gate(space, make_actor("gate-source"))
    staff = client.post(
        reverse("devices:admin-device-list", args=[space.pk]),
        {"kind": "printer", "name": "Frozen"}, format="json",
    )
    assert staff.status_code == 423
    assert _challenge(created["enrollment"]).status_code == 423
    assert client.post(reverse("devices:admin-device-revoke", args=[created["device"]["id"]])).status_code == 423
    assert Device.objects.filter(makerspace=space).count() == 1
    assert not DeviceEvent.objects.filter(event_type="revoked").exists()


def test_object_routes_resolve_their_tenant_from_pk():
    space = device_space("gate-origin")
    _manager, client = staff_client(space, "gate-origin-mgr")
    created = create_device(client, space)
    for name, pk in (
        ("devices:admin-device-detail", created["device"]["id"]),
        ("devices:admin-device-revoke", created["device"]["id"]),
        ("devices:admin-device-enrollment-create", created["device"]["id"]),
        ("devices:device-enrollment-challenge", created["enrollment"]["enrollment_id"]),
        ("devices:device-enrollment-complete", created["enrollment"]["enrollment_id"]),
    ):
        request = RequestFactory().post(reverse(name, args=[pk]))
        request.resolver_match = resolve(request.path_info)
        _url, targets, invalid, recognized = request_route_targets(request)
        assert (targets, invalid, recognized) == ({space.pk}, False, True), name


def test_completion_after_revocation_of_the_enrollment_is_gone():
    space = device_space("gate-revoked-enrollment")
    _manager, client = staff_client(space, "gate-revoked-mgr")
    created = create_device(client, space)
    client.post(reverse("devices:admin-device-enrollment-create", args=[created["device"]["id"]]))
    assert _challenge(created["enrollment"]).status_code == 410
    fresh = DeviceEnrollment.objects.get(device_id=created["device"]["id"], revoked_at__isnull=True)
    assert fresh.purpose == "enroll"
