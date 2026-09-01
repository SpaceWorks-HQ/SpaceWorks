import hashlib
import hmac
import io
import time

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import resolve
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient as ApiClientModel
from apps.apiclients.scope_registry import LEGACY_SCOPE
from apps.inventory.middleware import WOULD_REJECT_EVENT


pytestmark = pytest.mark.django_db

PUBLIC = "/api/v1/public/makerspaces/"
ORIGIN = "https://staging-client.example"
PREFIXES = ["/api/public/", "/api/v1/public/"]
NONCE = "staging-nonce-value"


def _server_client(label="staging server"):
    return ApiClientModel.issue(
        label=label,
        allowed_origins=[ORIGIN],
        client_type="server",
        scopes=["public:read"],
    )


def _signed_headers(client, secret, *, nonce=NONCE, signature=None):
    timestamp = str(int(time.time()))
    message = b"\n".join(
        [b"GET", PUBLIC.encode(), timestamp.encode(), nonce.encode(), b""]
    )
    return {
        "HTTP_X_CLIENT_ID": client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature
        or hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        "HTTP_X_NONCE": nonce,
    }


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PREFIXES,
)
def test_unsigned_request_succeeds_and_emits_one_would_reject_log(caplog):
    with caplog.at_level("WARNING", logger="apps.inventory.middleware"):
        response = APIClient().get(PUBLIC, HTTP_ORIGIN=ORIGIN)

    records = [
        record for record in caplog.records
        if record.getMessage() == WOULD_REJECT_EVENT
    ]
    assert response.status_code == 200
    assert len(records) == 1
    record = records[0]
    assert record.view_name == resolve(PUBLIC).view_name
    assert record.method == "GET"
    assert record.client_id is None
    assert record.hmac_credentials_present is False
    assert record.origin_present is True
    assert record.origin == ORIGIN
    assert record.reason == "no credentials"


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PREFIXES,
)
def test_would_reject_log_never_contains_signature_nonce_or_secret(caplog):
    client, secret = _server_client("sensitive-log-client")
    signature = "signature-private-value"
    nonce = "nonce-private-value"

    with caplog.at_level("WARNING", logger="apps.inventory.middleware"):
        response = APIClient().get(
            PUBLIC,
            **_signed_headers(client, secret, nonce=nonce, signature=signature),
        )

    record = next(r for r in caplog.records if r.getMessage() == WOULD_REJECT_EVENT)
    assert response.status_code == 401  # X-Nonce opts into fail-closed validation.
    assert record.reason == "bad signature"
    assert record.hmac_credentials_present is True
    rendered = record.getMessage() + repr(record.__dict__)
    assert signature not in rendered
    assert nonce not in rendered
    assert secret not in rendered
    assert "signature" not in record.__dict__
    assert "nonce" not in record.__dict__


@override_settings(
    API_CLIENT_AUTH_REQUIRED=True,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PREFIXES,
)
def test_enforcement_flag_alone_turns_unsigned_request_into_401():
    assert APIClient().get(PUBLIC).status_code == 401


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PREFIXES,
)
def test_opt_in_nonce_replay_is_rejected_while_nonce_requirement_is_off():
    client, secret = _server_client()
    headers = _signed_headers(client, secret)

    assert APIClient().get(PUBLIC, **headers).status_code == 200
    assert APIClient().get(PUBLIC, **headers).status_code == 401


@override_settings(
    API_CLIENT_AUTH_REQUIRED=True,
    APICLIENT_REQUIRE_NONCE=False,
    HMAC_PROTECTED_PATH_PREFIXES=PREFIXES,
)
def test_signed_server_client_does_not_need_an_origin_header():
    client, secret = _server_client("originless server")

    response = APIClient().get(
        PUBLIC,
        **_signed_headers(client, secret, nonce="originless-server-nonce"),
    )

    assert response.status_code == 200


def test_enforcement_report_names_legacy_client():
    client, _secret = ApiClientModel.issue(
        label="legacy report client",
        allowed_origins=[ORIGIN],
        scopes=[LEGACY_SCOPE],
    )
    output = io.StringIO()

    call_command("api_client_enforcement_report", stdout=output)

    report = output.getvalue()
    assert "legacy:v1=1" in report
    assert client.client_id in report
    assert "legacy report client" in report


def test_enforcement_settings_default_to_off():
    assert settings.API_CLIENT_AUTH_REQUIRED is False
    assert settings.APICLIENT_REQUIRE_NONCE is False
