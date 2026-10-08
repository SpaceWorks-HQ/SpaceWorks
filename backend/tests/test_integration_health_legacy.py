"""Integration health reports room-less (legacy-column) chat failures too (cloud lane).

A space that never created destinations still posts through the makerspace-wide Slack /
Mattermost / Discord webhook and Telegram chat id. Health reported those channels as a
configured-or-not boolean only, so a revoked makerspace webhook failed every alert with no
"last delivery failed" anywhere in the console. `legacy_deliveries` gives that path the
same counts a room gets; `legacy_channels` keeps its boolean shape for existing readers.
"""

import pytest

from apps.integrations import webhooks
from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.health import build_integration_health
from apps.integrations.notification_enums import NotificationFeature
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


def _fan_out(space, channel):
    return dispatch_channel(
        makerspace=space, channel=channel, feature=NotificationFeature.MAINTENANCE,
        event="logged", text_body="Machine needs attention", sync=True,
    )


def test_a_failing_makerspace_webhook_surfaces_as_a_legacy_failure(monkeypatch):
    space = make_space("health-legacy-fail")
    space.set_slack_webhook_url("https://hooks.example/revoked")
    space.save()

    def revoked(makerspace, *, channel, text, destination=None):
        raise webhooks.WebhookDeliveryError("404 from provider")

    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", revoked)
    _fan_out(space, "slack")

    section = build_integration_health(space)["chat_destinations"]

    assert section["legacy_channels"]["slack"] is True  # unchanged shape
    slack = section["legacy_deliveries"]["slack"]
    assert slack["configured"] is True
    assert slack["failed"] == 1
    assert slack["last_failure"]["error"].startswith("notification_delivery_failed:")
    assert "hooks.example" not in repr(section)
    assert section["status"] == "warn"
    assert build_integration_health(space)["status"] == "warn"


def test_a_healthy_legacy_channel_reports_its_last_send(monkeypatch):
    space = make_space("health-legacy-ok")
    space.set_discord_webhook_url("https://hooks.example/discord")
    space.save()
    monkeypatch.setattr(
        "apps.integrations.webhooks.send_webhook",
        lambda makerspace, *, channel, text, destination=None: True,
    )
    _fan_out(space, "discord")

    section = build_integration_health(space)["chat_destinations"]
    discord = section["legacy_deliveries"]["discord"]

    assert discord["failed"] == 0
    assert discord["last_failure"] is None
    assert discord["last_sent_at"] is not None
    assert section["status"] == "ok"


def test_an_unconfigured_legacy_channel_is_reported_as_such():
    space = make_space("health-legacy-none")

    legacy = build_integration_health(space)["chat_destinations"]["legacy_deliveries"]

    assert legacy["mattermost"] == {
        "configured": False, "last_sent_at": None, "failed": 0, "last_failure": None,
    }
