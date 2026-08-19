"""The signed message must not be ambiguous about whether a nonce was sent.

`METHOD \n PATH \n TIMESTAMP [\n NONCE] \n BODY` includes the nonce part only when
X-Nonce is present, so a nonced request and a nonce-less request whose body is
`NONCE + "\n" + body` encode to identical bytes. Before this was closed, replaying a
captured nonced request that way verified against the same signature and never claimed
the nonce -- defeating replay protection for the whole clock-skew window.
"""
import hashlib
import hmac
import time

import pytest
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.inventory.middleware import AMBIGUOUS_NONCE_BODY_EVENT

pytestmark = pytest.mark.django_db

PUBLIC = "/api/v1/public/makerspaces/"
ORIGIN = "https://canonicalization.example"
NONCE = "canonical-nonce-value"


@pytest.fixture(autouse=True)
def _protocol_settings(settings):
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.APICLIENT_REQUIRE_NONCE = False
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]


def _client():
    return ApiClient.issue(
        label="canonicalization client",
        allowed_origins=[ORIGIN],
        client_type="server",
        scopes=["public:read"],
    )


def _sign(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def test_a_nonced_signature_cannot_be_replayed_with_the_nonce_in_the_body(caplog):
    client, secret = _client()
    timestamp = str(int(time.time()))
    nonced = b"\n".join(
        [b"GET", PUBLIC.encode(), timestamp.encode(), NONCE.encode(), b""]
    )
    signature = _sign(secret, nonced)

    first = APIClient().get(
        PUBLIC,
        HTTP_X_CLIENT_ID=client.client_id,
        HTTP_X_TIMESTAMP=timestamp,
        HTTP_X_SIGNATURE=signature,
        HTTP_X_NONCE=NONCE,
        HTTP_ORIGIN=ORIGIN,
    )
    assert first.status_code == 200

    replay_body = (NONCE + "\n").encode()
    # The whole point: the two encodings are byte-identical, so the signature is valid
    # for both readings and only a body-shape check can tell them apart.
    assert b"\n".join(
        [b"GET", PUBLIC.encode(), timestamp.encode(), replay_body]
    ) == nonced

    with caplog.at_level("WARNING", logger="apps.inventory.middleware"):
        replay = APIClient().generic(
            "GET",
            PUBLIC,
            data=replay_body,
            content_type="application/octet-stream",
            HTTP_X_CLIENT_ID=client.client_id,
            HTTP_X_TIMESTAMP=timestamp,
            HTTP_X_SIGNATURE=signature,
            HTTP_ORIGIN=ORIGIN,
        )

    assert replay.status_code == 401
    assert any(
        record.getMessage() == AMBIGUOUS_NONCE_BODY_EVENT for record in caplog.records
    )


def test_an_ordinary_nonce_less_json_request_is_unaffected():
    client, secret = _client()
    timestamp = str(int(time.time()))
    body = b'{"query": "value"}'
    message = b"\n".join([b"GET", PUBLIC.encode(), timestamp.encode(), body])

    response = APIClient().generic(
        "GET",
        PUBLIC,
        data=body,
        content_type="application/json",
        HTTP_X_CLIENT_ID=client.client_id,
        HTTP_X_TIMESTAMP=timestamp,
        HTTP_X_SIGNATURE=_sign(secret, message),
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 200


def test_a_body_whose_first_line_is_not_nonce_shaped_is_unaffected():
    client, secret = _client()
    timestamp = str(int(time.time()))
    body = b"not a nonce because of spaces\nrest"
    message = b"\n".join([b"GET", PUBLIC.encode(), timestamp.encode(), body])

    response = APIClient().generic(
        "GET",
        PUBLIC,
        data=body,
        content_type="application/octet-stream",
        HTTP_X_CLIENT_ID=client.client_id,
        HTTP_X_TIMESTAMP=timestamp,
        HTTP_X_SIGNATURE=_sign(secret, message),
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 200
