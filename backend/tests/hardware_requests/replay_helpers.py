"""Real Station/lease setup, with object storage isolated from protocol tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.makerspaces import kiosk_station_services as stations
from apps.makerspaces import station_operator_leases as leases
from tests.events.checkin_helpers import make_staff
from tests.hardware_requests.test_kiosk_online import kiosk_space
from tests.return_helpers import make_accepted_request, make_box, make_product


@pytest.fixture
def replay_env(settings, monkeypatch):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    settings.EVENT_STATION_PIN_PEPPER = "test-only-independent-station-pepper"
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5000"]
    space = kiosk_space("replay-space")
    user = make_staff(space)
    station, credential, pin = stations.create_station(space, actor=user, name="Replay desk", kind="handover")
    station, credential, session_id, cookie, expires = stations.start_session(credential.public_token, pin=pin)
    lease, token = leases.issue_lease(station=station, credential=credential, session_id=session_id,
                                    session_expires_at=expires, user=user)
    client = APIClient()
    client.cookies[stations.COOKIE_NAME] = cookie
    headers = {"HTTP_ORIGIN": "http://localhost:5000", "HTTP_X_STATION_CSRF": "1",
               "HTTP_X_KIOSK_OPERATOR_LEASE": token}
    product = make_product(space)
    request = make_accepted_request(space, product, 1)
    # A real acceptance reserves the accepted quantity; this helper writes the row
    # directly, so mirror the reservation (as tests/test_issue.py's helper does) or the
    # replayed issue meets reserved=0 and fails as inventory_unavailable.
    product.available_quantity -= 1
    product.reserved_quantity += 1
    product.save(update_fields=["available_quantity", "reserved_quantity", "updated_at"])
    box = make_box(space)
    def presign(key, mime):
        return {"url": "http://storage.test/upload", "fields": {"key": f"staging/{key}", "Content-Type": mime}}
    monkeypatch.setattr("apps.evidence.services_upload.presigned_upload", presign)
    monkeypatch.setattr("apps.hardware_requests.replay_prepare.presigned_upload", presign)
    monkeypatch.setattr("apps.evidence.storage.delete_object", lambda key: None)
    monkeypatch.setattr("apps.evidence.storage.copy_object", lambda src, dst: None)
    monkeypatch.setattr("apps.hardware_requests.notifications.notify_request_issued", lambda row: None)
    monkeypatch.setattr("apps.hardware_requests.notifications.notify_request_returned", lambda row: None)
    return SimpleNamespace(space=space, user=user, station=station, credential=credential, lease=lease,
                           client=client, headers=headers, product=product, request=request, box=box)


def envelope(env, kind="assign_box", payload=None, **overrides):
    data = {"client_command_id": str(uuid4()), "aggregate_id": str(uuid4()), "sequence": 1,
            "kind": kind, "version": 1, "client_created_at": timezone.now().isoformat(),
            "payload": payload if payload is not None else {"request_id": env.request.pk, "box_code": env.box.code}}
    if kind != "assign_box":
        data["evidence"] = {"evidence_type": "return" if kind.endswith("return") else "issue",
                            "content_type": "image/jpeg", "size_bytes": 123}
    data.update(overrides)
    return data


def prepare(env, data):
    return env.client.post(reverse("kiosk-replay-prepare", kwargs={"public_token": env.credential.public_token}),
                           data, format="json", **env.headers)


def execute(env, data):
    return env.client.post(reverse("kiosk-replay-execute", kwargs={"public_token": env.credential.public_token,
                           "client_command_id": data["client_command_id"]}), data, format="json", **env.headers)


def identity(env):
    from apps.hardware_requests.replay_authorization import ReplayIdentity
    return ReplayIdentity(env.station.pk, env.lease.station_session_id, env.lease.station_version,
                          env.lease.pk, env.user.pk, env.lease.expires_at, env.credential.public_token)


def validated(data):
    from apps.hardware_requests.replay_serializers import ReplayEnvelopeSerializer
    serializer = ReplayEnvelopeSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data
