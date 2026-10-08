"""Every outbound chat/webhook channel under every provider failure (cloud-completeness lane).

`test_webhook_channel.py` and `test_telegram_integration.py` pin the contract with the
transport mocked out wholesale. This file goes one layer down -- the HTTP status and the
socket error the provider actually produces -- and walks the same matrix across all five
channels, because "Slack is tested" has repeatedly been read as "Discord is tested":

* a 2xx marks the row SENT;
* a timeout, refused connection, malformed response, 4xx, 429 or 5xx marks it FAILED with a
  *retryable* error code (the Celery task only retries `notification_delivery_failed:*`),
  never raises into the caller, and never writes the endpoint into the stored error --
  a chat webhook URL and a Telegram bot token are bearer credentials.
"""

import http.client
import io
import logging
import socket
from urllib import error as urllib_error

import pytest

from apps.integrations import telegram, webhooks
from apps.integrations.dispatch_channels import _deliver_notification
from apps.integrations.models import NotificationDeliveryLog, NotificationDestination
from apps.integrations.notification_enums import (
    NotificationDeliveryStatus,
    NotificationFeature,
)
from apps.integrations.tasks import _should_retry_notification
from apps.makerspaces.module_install import install_module
from apps.makerspaces.platform import module_enabled
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

SECRET_URL = "https://hooks.example.org/services/T000/B000/very-secret-path"
BOT_TOKEN = "123456:SECRET-bot-token-value"
SIGNING_SECRET = "correct-horse-battery-staple-32"

WEBHOOK_CHANNELS = ("slack", "mattermost", "discord", "webhook")

HTTP_FAILURES = (400, 401, 403, 404, 410, 429, 500, 502, 503)
SOCKET_FAILURES = (
    socket.timeout("timed out"),
    ConnectionRefusedError("refused"),
    http.client.BadStatusLine("garbage"),
    http.client.RemoteDisconnected("closed"),
)


def _space(slug, channel):
    space = make_space(slug)
    if not module_enabled(space, channel):
        install_module(space, channel, actor=None)
    return space


def _destination(space, channel):
    dest = NotificationDestination(
        makerspace=space, channel=channel, label=f"{channel} room", is_active=True
    )
    if channel == "telegram":
        dest.telegram_chat_id = "-100200300"
    else:
        dest.set_webhook_url(SECRET_URL)
        if channel == "webhook":
            dest.set_signing_secret(SIGNING_SECRET)
    dest.save()
    return dest


def _log(space, dest):
    return NotificationDeliveryLog.objects.create(
        makerspace=space,
        channel=dest.channel,
        destination=dest,
        destination_label=dest.label,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request.accepted",
        text_body="Request #12 accepted",
        payload={"request_id": 12},
    )


def _fake_transport(monkeypatch, outcome):
    """Replace DNS resolution and the pinned HTTPS POST with a canned provider answer."""
    monkeypatch.setattr(webhooks, "resolve_webhook_target", lambda url: object())

    def post(target, payload, extra_headers=None):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome, None

    monkeypatch.setattr(webhooks, "_post_to_target", post)


def _assert_failed_retryably(log):
    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.attempts == 1
    assert log.error.startswith("notification_delivery_failed:")
    assert _should_retry_notification(log) is True
    assert "hooks.example.org" not in log.error
    assert BOT_TOKEN not in log.error


@pytest.mark.parametrize("channel", WEBHOOK_CHANNELS)
def test_webhook_channels_mark_a_2xx_as_sent(monkeypatch, channel):
    space = _space(f"pf-ok-{channel}", channel)
    log = _log(space, _destination(space, channel))
    _fake_transport(monkeypatch, 204)

    _deliver_notification(log)

    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.SENT
    assert log.sent_at is not None


@pytest.mark.parametrize("status", HTTP_FAILURES)
@pytest.mark.parametrize("channel", WEBHOOK_CHANNELS)
def test_webhook_channels_record_http_errors_as_retryable_failures(
    monkeypatch, channel, status
):
    space = _space(f"pf-{channel}-{status}", channel)
    log = _log(space, _destination(space, channel))
    _fake_transport(monkeypatch, status)

    _deliver_notification(log)  # must not raise

    _assert_failed_retryably(log)


@pytest.mark.parametrize("error", SOCKET_FAILURES, ids=lambda e: type(e).__name__)
@pytest.mark.parametrize("channel", WEBHOOK_CHANNELS)
def test_webhook_channels_record_transport_errors_as_retryable_failures(
    monkeypatch, channel, error
):
    space = _space(f"pf-{channel}-{type(error).__name__.lower()}", channel)
    log = _log(space, _destination(space, channel))
    _fake_transport(monkeypatch, error)

    _deliver_notification(log)

    _assert_failed_retryably(log)


@pytest.mark.parametrize("channel", WEBHOOK_CHANNELS)
def test_webhook_channels_refuse_an_endless_redirect_chain(monkeypatch, channel):
    space = _space(f"pf-redirect-{channel}", channel)
    log = _log(space, _destination(space, channel))
    monkeypatch.setattr(webhooks, "resolve_webhook_target", lambda url: object())
    hops = []

    def post(target, payload, extra_headers=None):
        hops.append(1)
        return 302, "https://hooks.example.org/next"

    monkeypatch.setattr(webhooks, "_post_to_target", post)

    _deliver_notification(log)

    _assert_failed_retryably(log)
    assert len(hops) == webhooks._MAX_REDIRECTS + 1


# --------------------------------------------------------------------------- Telegram


def _telegram_space(slug, monkeypatch, settings):
    space = _space(slug, "telegram")
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    return space


class _Response(io.BytesIO):
    def __init__(self, status):
        super().__init__(b'{"ok": true}')
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_telegram_marks_a_2xx_as_sent(monkeypatch, settings):
    space = _telegram_space("pf-tg-ok", monkeypatch, settings)
    log = _log(space, _destination(space, "telegram"))
    seen = {}

    def urlopen(req, timeout):
        seen["url"], seen["timeout"] = req.full_url, timeout
        return _Response(200)

    monkeypatch.setattr(telegram.urllib_request, "urlopen", urlopen)

    _deliver_notification(log)

    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.SENT
    assert seen["timeout"] == 5
    assert seen["url"].endswith(f"/bot{BOT_TOKEN}/sendMessage")


@pytest.mark.parametrize("status", HTTP_FAILURES)
def test_telegram_http_errors_are_retryable_and_never_leak_the_token(
    monkeypatch, settings, caplog, status
):
    space = _telegram_space(f"pf-tg-{status}", monkeypatch, settings)
    log = _log(space, _destination(space, "telegram"))

    def urlopen(req, timeout):
        raise urllib_error.HTTPError(req.full_url, status, "provider said no", {}, None)

    monkeypatch.setattr(telegram.urllib_request, "urlopen", urlopen)

    with caplog.at_level(logging.DEBUG):
        _deliver_notification(log)

    _assert_failed_retryably(log)
    assert BOT_TOKEN not in caplog.text


@pytest.mark.parametrize(
    "error",
    (
        urllib_error.URLError(ConnectionRefusedError("refused")),
        socket.timeout("timed out"),
        http.client.RemoteDisconnected("closed"),
    ),
    ids=lambda e: type(e).__name__,
)
def test_telegram_transport_errors_are_retryable(monkeypatch, settings, caplog, error):
    space = _telegram_space(f"pf-tg-{type(error).__name__.lower()}", monkeypatch, settings)
    log = _log(space, _destination(space, "telegram"))

    def urlopen(req, timeout):
        raise error

    monkeypatch.setattr(telegram.urllib_request, "urlopen", urlopen)

    with caplog.at_level(logging.DEBUG):
        _deliver_notification(log)

    _assert_failed_retryably(log)
    assert BOT_TOKEN not in caplog.text


def test_telegram_without_any_bot_token_is_a_terminal_not_configured_row(
    monkeypatch, settings
):
    space = _space("pf-tg-unconfigured", "telegram")
    settings.TELEGRAM_BOT_TOKEN = ""
    log = _log(space, _destination(space, "telegram"))
    monkeypatch.setattr(
        telegram.urllib_request, "urlopen", lambda *a, **k: pytest.fail("must not send")
    )

    _deliver_notification(log)

    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_channel_not_configured"
    assert _should_retry_notification(log) is False
