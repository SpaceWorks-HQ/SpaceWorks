"""Part K1 — persistence, secrets, and default catalog for the notification matrix."""
import socket

import pytest

from apps.admin_api.api_client_serializers import ApiIntegrationSettingsSerializer
from apps.integrations.models import (
    EmailNotificationMute,
    NotificationChannel,
    NotificationFeature,
    NotificationPreference,
)
from apps.integrations.notification_catalog import (
    DEFAULT_CHANNEL_STATE,
    default_state,
    is_notification_enabled,
)
from apps.integrations.webhook_validation import validate_webhook_url
from rest_framework import serializers as drf_serializers
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

WEBHOOK = "https://hooks.slack.com/services/T000/B000/xyz"


@pytest.fixture(autouse=True)
def public_webhook_dns(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", port),
            )
        ],
    )


def test_webhook_fields_fernet_round_trip():
    space = make_space("k1-crypto")
    space.set_slack_webhook_url(WEBHOOK)
    space.set_mattermost_webhook_url("https://mm.example.org/hooks/abc")
    space.save()
    space.refresh_from_db()
    # Stored value is ciphertext, not the plaintext.
    assert space.slack_webhook_url != WEBHOOK
    assert space.slack_webhook_url.startswith("fernet:")
    assert space.get_slack_webhook_url() == WEBHOOK
    assert space.get_mattermost_webhook_url() == "https://mm.example.org/hooks/abc"
    # Blank clears.
    space.set_slack_webhook_url("")
    assert space.slack_webhook_url == ""
    assert space.get_slack_webhook_url() == ""


def test_integration_serializer_never_returns_webhook_value_but_sets_flag():
    space = make_space("k1-serial")
    space.set_slack_webhook_url(WEBHOOK)
    space.save()
    data = ApiIntegrationSettingsSerializer(space).data
    assert "slack_webhook_url" not in data  # write-only, never serialized
    assert data["slack_webhook_url_set"] is True
    assert data["mattermost_webhook_url_set"] is False


def test_integration_serializer_writes_and_clears_webhook():
    space = make_space("k1-write")
    ser = ApiIntegrationSettingsSerializer(
        space, data={"slack_webhook_url": WEBHOOK}, partial=True
    )
    ser.is_valid(raise_exception=True)
    ser.save()
    space.refresh_from_db()
    assert space.get_slack_webhook_url() == WEBHOOK
    # Omitting the field preserves; blank clears.
    ser2 = ApiIntegrationSettingsSerializer(
        space, data={"telegram_group_chat_id": "123"}, partial=True
    )
    ser2.is_valid(raise_exception=True)
    ser2.save()
    space.refresh_from_db()
    assert space.get_slack_webhook_url() == WEBHOOK  # preserved
    ser3 = ApiIntegrationSettingsSerializer(
        space, data={"slack_webhook_url": ""}, partial=True
    )
    ser3.is_valid(raise_exception=True)
    ser3.save()
    space.refresh_from_db()
    assert space.get_slack_webhook_url() == ""


@pytest.mark.parametrize(
    "bad",
    [
        "http://hooks.slack.com/x",  # not https
        "ftp://hooks.slack.com/x",
        "https://user:pass@hooks.slack.com/x",  # embedded credentials
        "https://hooks.slack.com/x#frag",  # fragment
        "not-a-url",
    ],
)
def test_webhook_validation_rejects_bad(bad):
    with pytest.raises(drf_serializers.ValidationError):
        validate_webhook_url(bad)


def test_webhook_validation_accepts_https_and_blank():
    assert validate_webhook_url(WEBHOOK) == WEBHOOK
    assert validate_webhook_url("https://mm.self-hosted.example/hooks/z") != ""
    assert validate_webhook_url("") == ""
    assert validate_webhook_url("  ") == ""


def test_default_channel_state_matches_spec():
    F, C = NotificationFeature, NotificationChannel
    assert default_state(F.HARDWARE_REQUESTS, C.EMAIL) is True
    assert default_state(F.HARDWARE_REQUESTS, C.TELEGRAM) is True
    assert default_state(F.PRINTING, C.EMAIL) is True
    assert default_state(F.PRINTING, C.TELEGRAM) is False
    assert default_state(F.BOOKINGS, C.TELEGRAM) is True
    assert default_state(F.EVENTS, C.EMAIL) is False
    assert default_state(F.MAINTENANCE, C.EMAIL) is False
    # Slack/Mattermost always default off.
    for feature in DEFAULT_CHANNEL_STATE:
        assert default_state(feature, C.SLACK) is False
        assert default_state(feature, C.MATTERMOST) is False


def test_is_notification_enabled_override_wins_and_is_isolated():
    space = make_space("k1-resolve")
    F, C = NotificationFeature, NotificationChannel
    # No row → catalog default.
    assert is_notification_enabled(space, F.EVENTS, C.SLACK) is False
    # Explicit override flips one cell.
    NotificationPreference.objects.create(
        makerspace=space, feature=F.EVENTS, channel=C.SLACK, enabled=True
    )
    assert is_notification_enabled(space, F.EVENTS, C.SLACK) is True
    # Other cells untouched.
    assert is_notification_enabled(space, F.EVENTS, C.EMAIL) is False
    assert is_notification_enabled(space, F.HARDWARE_REQUESTS, C.EMAIL) is True
    # An override can also turn a default-on cell OFF.
    NotificationPreference.objects.create(
        makerspace=space, feature=F.HARDWARE_REQUESTS, channel=C.EMAIL, enabled=False
    )
    assert is_notification_enabled(space, F.HARDWARE_REQUESTS, C.EMAIL) is False


def test_notification_preference_does_not_touch_email_mutes():
    space = make_space("k1-additive")
    NotificationPreference.objects.create(
        makerspace=space,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        channel=NotificationChannel.EMAIL,
        enabled=False,
    )
    # The legacy exact-row mute table is entirely independent.
    assert EmailNotificationMute.objects.filter(makerspace=space).count() == 0
