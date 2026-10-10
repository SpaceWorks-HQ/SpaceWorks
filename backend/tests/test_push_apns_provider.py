"""The APNs sender under every Apple answer (cloud lane).

Drives the real `send_apns` with only `httpx.Client` replaced. BadDeviceToken and
Unregistered retire the device; every other refusal, a non-JSON body and a transport error
are retryable; an incomplete or unusable key is a configuration error. The development
environment must go to Apple's sandbox host, production to the live one.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import httpx

from apps.integrations import push_apns
from apps.integrations.models_push import PlatformPushSettings
from apps.integrations.push_fcm import PushProviderError

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def pem():
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _row(pem, **overrides):
    row = PlatformPushSettings.load()
    row.apns_team_id = overrides.get("team", "TEAMID1234")
    row.apns_key_id = overrides.get("key_id", "KEYID12345")
    row.apns_topic = overrides.get("topic", "org.spaceworks.app")
    row.set_apns_private_key(overrides.get("key", pem))
    row.save()
    return row


class _Response:
    def __init__(self, status, payload=None, invalid_json=False):
        self.status_code = status
        self._payload = payload
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("not json")
        return self._payload


def _apple(monkeypatch, outcome):
    seen = []

    class Client:
        def __init__(self, **kwargs):
            seen.append(("client", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, **kwargs):
            seen.append((url, kwargs))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(push_apns.httpx, "Client", Client)
    return seen


@pytest.mark.parametrize(
    "environment,host",
    [("development", "api.sandbox.push.apple.com"), ("production", "api.push.apple.com")],
)
def test_a_delivered_alert_goes_to_the_right_host_with_a_signed_token(
    monkeypatch, pem, environment, host
):
    seen = _apple(monkeypatch, _Response(200))

    push_apns.send_apns(_row(pem), "device-hex", environment, "Space Works", "Body", {"e": "x"})

    client_kwargs = seen[0][1]
    url, kwargs = seen[1]
    assert client_kwargs == {"http2": True, "timeout": 10}
    assert url == f"https://{host}/3/device/device-hex"
    assert kwargs["headers"]["apns-topic"] == "org.spaceworks.app"
    assert kwargs["headers"]["authorization"].startswith("bearer ")


@pytest.mark.parametrize("reason", ["BadDeviceToken", "Unregistered"])
def test_a_dead_device_is_marked_invalid(monkeypatch, pem, reason):
    _apple(monkeypatch, _Response(410 if reason == "Unregistered" else 400, {"reason": reason}))

    with pytest.raises(PushProviderError) as raised:
        push_apns.send_apns(_row(pem), "dead", "production", "t", "b", {})
    assert raised.value.invalid_token is True


@pytest.mark.parametrize(
    "outcome",
    [
        _Response(429, {"reason": "TooManyRequests"}),
        _Response(500, {"reason": "InternalServerError"}),
        _Response(503, invalid_json=True),
        _Response(403, {"reason": "InvalidProviderToken"}),
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("down"),
    ],
    ids=["429", "500", "503-not-json", "403-provider-token", "timeout", "connect"],
)
def test_other_failures_are_retryable(monkeypatch, pem, outcome):
    _apple(monkeypatch, outcome)

    with pytest.raises(PushProviderError) as raised:
        push_apns.send_apns(_row(pem), "live", "production", "t", "b", {})
    assert raised.value.invalid_token is False


@pytest.mark.parametrize(
    "overrides", [{"team": ""}, {"key_id": ""}, {"topic": ""}, {"key": "not a pem key"}],
    ids=["no-team", "no-key-id", "no-topic", "bad-key"],
)
def test_an_incomplete_or_unusable_key_is_a_configuration_error(monkeypatch, pem, overrides):
    _apple(monkeypatch, _Response(200))

    with pytest.raises(PushProviderError, match="configuration"):
        push_apns.send_apns(_row(pem, **overrides), "token", "production", "t", "b", {})
