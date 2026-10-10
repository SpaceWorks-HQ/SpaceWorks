"""Shared device-test helpers: a space with `devices`, a manager, and protocol signing."""

import time
import uuid

from django.urls import reverse
from rest_framework.test import APIClient

from apps.devices import protocol
from apps.ed25519 import encode_key, generate_keypair, sign_bytes
from tests.return_helpers import make_member, make_space

HEARTBEAT = "/api/v1/device/heartbeat"


def device_space(slug, modules=("devices",)):
    space = make_space(slug)
    space.enabled_modules = sorted(set(space.enabled_modules or []) | set(modules))
    space.save(update_fields=["enabled_modules"])
    return space


def staff_client(space, name):
    manager = make_member(name, space)
    client = APIClient()
    client.force_authenticate(manager)
    return manager, client


def create_device(client, space, **body):
    payload = {"kind": "printer", "name": "Prusa MK4", **body}
    response = client.post(
        reverse("devices:admin-device-list", args=[space.pk]), payload, format="json"
    )
    assert response.status_code == 201, response.data
    return response.data


def enroll(enrollment, private_key=None, public_key=None, client=None):
    """Run challenge + complete for an enrollment grant; return (response, private, public)."""
    client = client or APIClient()
    if private_key is None:
        private_key, raw_public = generate_keypair()
        public_key = encode_key(raw_public)
    pk = enrollment["enrollment_id"]
    token = enrollment["token"]
    challenge = client.post(
        reverse("devices:device-enrollment-challenge", args=[pk]),
        {"token": token, "public_key": public_key}, format="json",
    )
    assert challenge.status_code == 200, challenge.data
    from apps.devices.models import DeviceEnrollment
    from apps.ed25519 import fingerprint_public_key

    row = DeviceEnrollment.objects.get(pk=pk)
    raw_challenge = protocol.b64url_decode(challenge.data["challenge"], label="challenge")
    message = protocol.enrollment_message(
        enrollment_id=row.pk, makerspace_id=row.makerspace_id, device_id=row.device_id,
        purpose=row.purpose, fingerprint=fingerprint_public_key(public_key),
        challenge=raw_challenge,
    )
    response = client.post(
        reverse("devices:device-enrollment-complete", args=[pk]),
        {
            "token": token, "public_key": public_key, "challenge": challenge.data["challenge"],
            "signature": encode_key(sign_bytes(message, private_key)),
        },
        format="json",
    )
    return response, private_key, public_key


def signed_headers(device_id, key_version, private_key, *, target=HEARTBEAT, body=b"",
                   method="POST", timestamp=None, nonce=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or protocol.b64url_encode(uuid.uuid4().bytes)
    message = protocol.request_message(
        method=method, raw_target=target, timestamp=timestamp, nonce=nonce, body=body,
    )
    return {
        "HTTP_X_DEVICE_ID": str(device_id),
        "HTTP_X_DEVICE_KEY_VERSION": str(key_version),
        "HTTP_X_DEVICE_SIGNATURE_VERSION": "v1",
        "HTTP_X_DEVICE_TIMESTAMP": str(timestamp),
        "HTTP_X_DEVICE_NONCE": nonce,
        "HTTP_X_DEVICE_SIGNATURE": encode_key(sign_bytes(message, private_key)),
        "REQUEST_URI": target,
    }


def heartbeat(headers, client=None):
    return (client or APIClient()).post(HEARTBEAT, data=b"", content_type="application/json", **headers)


def active_device(slug):
    """An enrolled device: (space, manager, staff client, device id, private key)."""
    space = device_space(slug)
    manager, client = staff_client(space, f"{slug}-manager")
    created = create_device(client, space)
    response, private_key, _public = enroll(created["enrollment"])
    assert response.status_code == 200, response.data
    return space, manager, client, created["device"]["id"], private_key
