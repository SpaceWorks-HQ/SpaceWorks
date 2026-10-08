"""The FCM sender under every Google answer (cloud lane).

`test_native_push.py` mocks `send_fcm` wholesale. This drives the real function with only
`requests.post` replaced, because its classification is what decides whether a device is
deactivated (`invalid_token`) or the delivery is retried: an UNREGISTERED / NOT_FOUND token
must be retired, every other failure must be retryable, and a broken service account must
be a configuration error rather than an exception out of the sender.
"""

import json

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.integrations.models_push import PlatformPushSettings
from apps.integrations.push_fcm import PushProviderError, send_fcm

pytestmark = pytest.mark.django_db


def _private_key_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture(scope="module")
def pem():
    return _private_key_pem()


def _row(pem, **account_overrides):
    account = {
        "client_email": "push@project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
        "project_id": "spaceworks-test",
        **account_overrides,
    }
    row = PlatformPushSettings.load()
    row.set_fcm_service_account(json.dumps(account))
    row.save()
    return row


class _Response:
    def __init__(self, status, payload=None, text=None):
        self.status_code = status
        self._payload = payload
        self._text = text

    def json(self):
        if self._text is not None:
            raise requests.JSONDecodeError("bad", self._text, 0)
        return self._payload


def _google(monkeypatch, oauth, send=None):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if "oauth2" in url:
            if isinstance(oauth, Exception):
                raise oauth
            return oauth
        if isinstance(send, Exception):
            raise send
        return send

    monkeypatch.setattr("apps.integrations.push_fcm.requests.post", post)
    return calls


def test_a_delivered_message_uses_the_oauth_token_and_a_timeout(monkeypatch, pem):
    calls = _google(monkeypatch, _Response(200, {"access_token": "ya29.token"}), _Response(200, {}))

    send_fcm(_row(pem), "device-token", "Space Works", "Body", {"event": "x"})

    send_url, send_kwargs = calls[1]
    assert send_url.endswith("/projects/spaceworks-test/messages:send")
    assert send_kwargs["headers"]["Authorization"] == "Bearer ya29.token"
    assert send_kwargs["json"]["message"]["token"] == "device-token"
    assert all(kwargs["timeout"] == 10 for _, kwargs in calls)


@pytest.mark.parametrize(
    "error",
    [
        {"status": "NOT_FOUND"},
        {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "UNREGISTERED"}]},
    ],
    ids=["not-found", "unregistered"],
)
def test_a_dead_device_token_is_marked_invalid(monkeypatch, pem, error):
    _google(monkeypatch, _Response(200, {"access_token": "t"}), _Response(404, {"error": error}))

    with pytest.raises(PushProviderError) as raised:
        send_fcm(_row(pem), "dead-token", "t", "b", {})
    assert raised.value.invalid_token is True


@pytest.mark.parametrize(
    "response",
    [
        _Response(500, {"error": {"status": "INTERNAL"}}),
        _Response(503, text="<html>unavailable</html>"),
        _Response(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}),
        _Response(403, {"error": {"status": "PERMISSION_DENIED"}}),
    ],
    ids=["500", "503-html", "429", "403"],
)
def test_a_provider_failure_is_retryable_not_a_dead_token(monkeypatch, pem, response):
    _google(monkeypatch, _Response(200, {"access_token": "t"}), response)

    with pytest.raises(PushProviderError) as raised:
        send_fcm(_row(pem), "live-token", "t", "b", {})
    assert raised.value.invalid_token is False


@pytest.mark.parametrize(
    "oauth",
    [
        _Response(401, {"error": "invalid_grant"}),
        _Response(200, {}),
        _Response(200, text="not json"),
        requests.Timeout("slow"),
        requests.ConnectionError("down"),
    ],
    ids=["401", "no-token", "not-json", "timeout", "connection"],
)
def test_an_authorization_failure_is_a_provider_error(monkeypatch, pem, oauth):
    calls = _google(monkeypatch, oauth, _Response(200, {}))

    with pytest.raises(PushProviderError) as raised:
        send_fcm(_row(pem), "token", "t", "b", {})
    assert raised.value.invalid_token is False
    assert len(calls) == 1  # never reached the send endpoint


def test_a_send_timeout_is_a_provider_error(monkeypatch, pem):
    _google(monkeypatch, _Response(200, {"access_token": "t"}), requests.Timeout("slow"))

    with pytest.raises(PushProviderError):
        send_fcm(_row(pem), "token", "t", "b", {})


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_email": ""},
        {"project_id": None},
        {"token_uri": "http://insecure.example/token"},
        {"private_key": "-----BEGIN PRIVATE KEY-----\nnot a key\n-----END PRIVATE KEY-----"},
    ],
    ids=["no-email", "no-project", "plain-http-token-uri", "unusable-private-key"],
)
def test_an_incomplete_service_account_is_a_configuration_error(monkeypatch, pem, overrides):
    _google(monkeypatch, _Response(200, {"access_token": "t"}), _Response(200, {}))

    with pytest.raises(PushProviderError, match="configuration"):
        send_fcm(_row(pem, **overrides), "token", "t", "b", {})


def test_a_service_account_that_is_not_json_is_a_configuration_error(monkeypatch):
    row = PlatformPushSettings.load()
    row.set_fcm_service_account("{not json")
    row.save()

    with pytest.raises(PushProviderError, match="configuration"):
        send_fcm(row, "token", "t", "b", {})
