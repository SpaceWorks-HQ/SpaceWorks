"""The Twilio provider under every vendor condition (cloud lane).

Phone sign-in tests mock `send_sms` wholesale, so the shipped provider never ran in the
suite. These drive the real `TwilioSmsProvider` with only `urlopen` replaced: what it
signs and sends, and that every vendor failure -- 4xx, 429, 5xx, timeout, refused
connection -- is a quiet `False` that never echoes the destination number or the auth
token into a log line. Unconfigured, partial, undecryptable and unknown-provider rows are
all "SMS is off", never an exception.
"""

import base64
import io
import logging
import socket
from urllib import error as urllib_error
from urllib import parse as urllib_parse

import pytest

from apps.integrations import sms
from apps.integrations.models_sms import PlatformSmsSettings
from apps.integrations.sms import twilio

pytestmark = pytest.mark.django_db

TOKEN = "twilio-auth-token-SECRET"
TO = "+14155550123"


def _configure(**overrides):
    row = PlatformSmsSettings.load()
    row.is_enabled = overrides.pop("is_enabled", True)
    row.provider = overrides.pop("provider", "twilio")
    row.account_sid = overrides.pop("account_sid", "AC0123456789")
    row.from_number = overrides.pop("from_number", "+14155550100")
    row.set_auth_token(overrides.pop("token", TOKEN))
    row.save()
    return row


class _Response(io.BytesIO):
    def __init__(self, status):
        super().__init__(b"{}")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_configured_provider_signs_and_sends_one_form_post(monkeypatch):
    _configure()
    seen = {}

    def urlopen(req, timeout):
        seen.update(url=req.full_url, timeout=timeout, auth=req.get_header("Authorization"))
        seen["body"] = urllib_parse.parse_qs(req.data.decode())
        return _Response(201)

    monkeypatch.setattr(twilio.urllib_request, "urlopen", urlopen)

    assert sms.send_sms(to=TO, body="Your code is 123456") is True
    assert seen["url"] == f"{twilio.API_ROOT}/Accounts/AC0123456789/Messages.json"
    assert seen["timeout"] == twilio.TIMEOUT_SECONDS
    assert seen["body"] == {"To": [TO], "From": ["+14155550100"], "Body": ["Your code is 123456"]}
    expected = base64.b64encode(f"AC0123456789:{TOKEN}".encode()).decode()
    assert seen["auth"] == f"Basic {expected}"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_a_vendor_http_error_is_false_and_logs_no_pii(monkeypatch, caplog, status):
    _configure()

    def urlopen(req, timeout):
        body = io.BytesIO(f'{{"message": "The number {TO} is unverified"}}'.encode())
        raise urllib_error.HTTPError(req.full_url, status, "rejected", {}, body)

    monkeypatch.setattr(twilio.urllib_request, "urlopen", urlopen)

    with caplog.at_level(logging.DEBUG):
        assert sms.send_sms(to=TO, body="code") is False

    record = next(r for r in caplog.records if r.getMessage() == "sms_send_rejected")
    assert record.status == status
    assert TO not in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    "error",
    [socket.timeout("timed out"), urllib_error.URLError(ConnectionRefusedError("refused"))],
    ids=["timeout", "refused"],
)
def test_a_transport_failure_is_false_not_an_exception(monkeypatch, caplog, error):
    _configure()

    def urlopen(req, timeout):
        raise error

    monkeypatch.setattr(twilio.urllib_request, "urlopen", urlopen)

    with caplog.at_level(logging.DEBUG):
        assert sms.send_sms(to=TO, body="code") is False
    assert "sms_send_failed" in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [{"account_sid": ""}, {"from_number": ""}, {"token": ""}, {"is_enabled": False}],
    ids=["no-sid", "no-from", "no-token", "switched-off"],
)
def test_an_incomplete_or_disabled_row_is_sms_off(monkeypatch, overrides):
    _configure(**overrides)
    monkeypatch.setattr(
        twilio.urllib_request, "urlopen", lambda *a, **k: pytest.fail("must not send")
    )

    assert sms.sms_configured() is False
    assert sms.send_sms(to=TO, body="code") is False


def test_an_undecryptable_token_is_sms_off_not_a_500(monkeypatch):
    row = _configure()
    PlatformSmsSettings.objects.filter(pk=row.pk).update(auth_token="fernet:not-a-fernet-token")
    monkeypatch.setattr(
        twilio.urllib_request, "urlopen", lambda *a, **k: pytest.fail("must not send")
    )

    assert sms.sms_configured() is False
    assert sms.send_sms(to=TO, body="code") is False


def test_an_unknown_stored_provider_is_sms_off():
    row = _configure()
    PlatformSmsSettings.objects.filter(pk=row.pk).update(provider="carrier-pigeon")

    assert sms.get_sms_provider() is None
    assert sms.send_sms(to=TO, body="code") is False


def test_a_provider_that_raises_never_reaches_the_caller(monkeypatch):
    _configure()
    monkeypatch.setattr(
        twilio.TwilioSmsProvider, "send", lambda self, *, to, body: 1 / 0
    )

    assert sms.send_sms(to=TO, body="code") is False
