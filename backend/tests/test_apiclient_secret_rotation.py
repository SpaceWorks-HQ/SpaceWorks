import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.apiclients.crypto import decrypt_secret
from apps.apiclients.models import ApiClient
from apps.audit.models import AuditLog
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db

PUBLIC_PATH = "/api/v1/public/makerspaces/"
ORIGIN = "https://rotation-client.example"


@pytest.fixture(autouse=True)
def _hmac_settings(settings):
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.APICLIENT_REQUIRE_NONCE = True
    settings.HMAC_MAX_CLOCK_SKEW_SECONDS = 300
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def rotation_client():
    makerspace = make_space("secret-rotation")
    manager = make_member("secret-rotation-manager", makerspace)
    api_client, secret = ApiClient.issue(
        label="Rotating server client",
        makerspace=makerspace,
        allowed_origins=[ORIGIN],
        created_by=manager,
        client_type="server",
    )
    return api_client, secret, authenticated_client(manager)


def _rotate(api_client, admin_client):
    return admin_client.post(
        f"/api/v1/admin/api-clients/{api_client.pk}/rotate-secret",
        format="json",
    )


def _signed_headers(api_client, secret, nonce):
    timestamp = str(int(time.time()))
    message = b"\n".join(
        [b"GET", PUBLIC_PATH.encode(), timestamp.encode(), nonce.encode(), b""]
    )
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_X_NONCE": nonce,
        "HTTP_ORIGIN": ORIGIN,
    }


def _get(api_client, secret, nonce):
    return APIClient().get(
        PUBLIC_PATH,
        **_signed_headers(api_client, secret, nonce),
    )


def test_new_and_previous_secrets_work_during_grace(rotation_client):
    api_client, previous_secret, admin_client = rotation_client

    rotated = _rotate(api_client, admin_client)
    assert rotated.status_code == 200
    new_secret = rotated.data["client_secret"]
    assert _get(api_client, new_secret, "rotation-new-secret").status_code == 200
    assert _get(api_client, previous_secret, "rotation-old-secret").status_code == 200


def test_previous_secret_is_rejected_after_explicit_expiry(rotation_client):
    api_client, previous_secret, admin_client = rotation_client
    rotated = _rotate(api_client, admin_client)
    assert rotated.status_code == 200
    new_secret = rotated.data["client_secret"]
    ApiClient.objects.filter(pk=api_client.pk).update(
        previous_secret_valid_until=timezone.now() - timedelta(seconds=1)
    )

    expired = _get(api_client, previous_secret, "rotation-expired-secret")
    current = _get(api_client, new_secret, "rotation-current-after-expiry")

    assert expired.status_code == 401
    assert current.status_code == 200


def test_second_rotation_replaces_first_previous_secret(rotation_client):
    api_client, first_secret, admin_client = rotation_client
    first_rotation = _rotate(api_client, admin_client)
    assert first_rotation.status_code == 200
    second_secret = first_rotation.data["client_secret"]
    second_rotation = _rotate(api_client, admin_client)

    assert second_rotation.status_code == 200
    assert _get(api_client, first_secret, "rotation-first-old").status_code == 401
    assert _get(api_client, second_secret, "rotation-second-old").status_code == 200


def test_nonce_replay_is_shared_across_current_and_previous(rotation_client):
    api_client, previous_secret, admin_client = rotation_client
    rotated = _rotate(api_client, admin_client)
    assert rotated.status_code == 200
    new_secret = rotated.data["client_secret"]
    nonce = "rotation-shared-nonce"

    first = _get(api_client, previous_secret, nonce)
    replay = _get(api_client, new_secret, nonce)

    assert first.status_code == 200
    assert replay.status_code == 401


def test_bad_signature_does_not_consume_nonce(rotation_client):
    api_client, _previous_secret, admin_client = rotation_client
    rotated = _rotate(api_client, admin_client)
    assert rotated.status_code == 200
    new_secret = rotated.data["client_secret"]
    nonce = "rotation-unclaimed-nonce"

    rejected = _get(api_client, "not-either-secret", nonce)
    accepted = _get(api_client, new_secret, nonce)

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_rotation_response_and_audit_never_expose_previous_secret(rotation_client):
    api_client, previous_secret, admin_client = rotation_client

    response = _rotate(api_client, admin_client)
    new_secret = response.data["client_secret"]
    audit_entry = AuditLog.objects.get(
        action="api_client.secret_rotated",
        target_id=str(api_client.pk),
    )
    response_text = json.dumps(response.data)
    audit_text = json.dumps(audit_entry.meta)
    api_client.refresh_from_db()

    assert response.status_code == 200
    assert previous_secret not in response_text
    assert "previous_secret" not in response.data
    assert previous_secret not in audit_text
    assert new_secret not in audit_text
    assert audit_entry.meta == {
        "grace_window_opened": True,
        "previous_secret_valid_until": api_client.previous_secret_valid_until.isoformat(),
    }


def test_rotation_atomically_keeps_distinct_current_and_previous(rotation_client):
    api_client, previous_secret, admin_client = rotation_client

    response = _rotate(api_client, admin_client)
    api_client.refresh_from_db()

    assert response.status_code == 200
    assert bytes(api_client.secret_encrypted) != bytes(
        api_client.previous_secret_encrypted
    )
    assert api_client.get_secret() != decrypt_secret(
        api_client.previous_secret_encrypted
    )
    assert decrypt_secret(api_client.previous_secret_encrypted) == previous_secret
