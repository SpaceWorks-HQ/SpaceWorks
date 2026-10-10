"""Provider JSON must not escape fail-safe classification or retire a live device."""

import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import InvalidToken

from apps.integrations import push_apns, push_fcm
from apps.integrations.push_fcm import PushProviderError


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.payload = payload

    def json(self):
        return self.payload


def fcm_row(payload):
    return SimpleNamespace(get_fcm_service_account=lambda: json.dumps(payload))


ACCOUNT = {
    "client_email": "push@example.org", "private_key": "key",
    "token_uri": "https://oauth2.googleapis.com/token", "project_id": "project",
}


@pytest.mark.parametrize("payload", [[], None, "account", {**ACCOUNT, "project_id": 123}])
def test_fcm_rejects_a_service_account_with_the_wrong_shape(payload):
    with pytest.raises(PushProviderError, match="configuration"):
        push_fcm.send_fcm(fcm_row(payload), "token", "title", "body", {})


@pytest.mark.parametrize("payload", [[], None, "token", {"access_token": []}, {"access_token": 5}])
def test_fcm_malformed_oauth_does_not_reach_delivery(monkeypatch, payload):
    monkeypatch.setattr(push_fcm.jwt, "encode", lambda *a, **k: "assertion")
    calls = []
    monkeypatch.setattr(
        push_fcm.requests, "post",
        lambda *a, **k: calls.append(a[0]) or Response(200, payload),
    )
    with pytest.raises(PushProviderError):
        push_fcm.send_fcm(fcm_row(ACCOUNT), "token", "title", "body", {})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload", [[], None, "error", {"error": "UNREGISTERED"},
                {"error": {"details": "UNREGISTERED"}}],
)
def test_fcm_malformed_error_does_not_retire_a_device(monkeypatch, payload):
    monkeypatch.setattr(push_fcm.jwt, "encode", lambda *a, **k: "assertion")
    responses = iter([Response(200, {"access_token": "token"}), Response(503, payload)])
    monkeypatch.setattr(push_fcm.requests, "post", lambda *a, **k: next(responses))
    with pytest.raises(PushProviderError) as raised:
        push_fcm.send_fcm(fcm_row(ACCOUNT), "token", "title", "body", {})
    assert raised.value.invalid_token is False
    assert str(raised.value) == "FCM delivery failed."


@pytest.mark.parametrize("payload", [[], None, "error", {"reason": ["Unregistered"]}])
def test_apns_malformed_error_is_retryable(monkeypatch, payload):
    row = SimpleNamespace(
        get_apns_private_key=lambda: "key", apns_team_id="team",
        apns_key_id="id", apns_topic="org.spaceworks",
    )
    monkeypatch.setattr(push_apns.jwt, "encode", lambda *a, **k: "signed")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            return Response(503, payload)

    monkeypatch.setattr(push_apns.httpx, "Client", Client)
    with pytest.raises(PushProviderError) as raised:
        push_apns.send_apns(row, "secret-device-token", "production", "t", "b", {})
    assert raised.value.invalid_token is False
    assert str(raised.value) == "APNs delivery failed."


@pytest.mark.parametrize("provider", ["fcm", "apns"])
def test_undecryptable_push_credentials_are_configuration_errors(provider):
    def unreadable():
        raise InvalidToken

    row = SimpleNamespace(get_fcm_service_account=unreadable, get_apns_private_key=unreadable)
    with pytest.raises(PushProviderError, match="configuration"):
        if provider == "fcm":
            push_fcm.send_fcm(row, "token", "title", "body", {})
        else:
            push_apns.send_apns(row, "token", "production", "title", "body", {})
