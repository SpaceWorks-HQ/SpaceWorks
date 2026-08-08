"""Phase 10 -- Discord as a channel, and one module key per notification channel.

Two things under test: that Discord behaves like the other webhook channels without
inheriting Slack's payload shape, and that the new per-channel module keys gate sending
without destroying stored credentials.
"""

import json
import pytest

from apps.admin_api.api_client_serializers import ApiIntegrationSettingsSerializer
from apps.integrations.dispatch_channels import channel_module_blocks, dispatch_channel
from apps.integrations.models import (
    NonEmailNotificationChannel,
    NotificationChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationFeature,
)
from apps.integrations.notification_catalog import DEFAULT_CHANNEL_STATE, default_state
from apps.makerspaces import module_registry
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/123/abcXYZ"
SLACK_WEBHOOK = "https://hooks.slack.com/services/T000/B000/xyz"
CHANNELS = ("slack", "mattermost", "discord")


def space_with_discord(slug="p10-discord"):
    space = make_space(slug)
    space.set_discord_webhook_url(DISCORD_WEBHOOK)
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"discord"})
    space.save()
    return space


# --- the channel itself ----------------------------------------------------------


def test_discord_webhook_fernet_round_trip():
    space = make_space("p10-crypto")
    space.set_discord_webhook_url(DISCORD_WEBHOOK)
    space.save()
    space.refresh_from_db()
    assert space.discord_webhook_url != DISCORD_WEBHOOK
    assert space.discord_webhook_url.startswith("fernet:")
    assert space.get_discord_webhook_url() == DISCORD_WEBHOOK
    space.set_discord_webhook_url("")
    assert space.get_discord_webhook_url() == ""


def test_serializer_never_returns_the_discord_webhook_but_flags_it():
    space = make_space("p10-serial")
    space.set_discord_webhook_url(DISCORD_WEBHOOK)
    space.save()
    data = ApiIntegrationSettingsSerializer(space).data
    assert "discord_webhook_url" not in data
    assert data["discord_webhook_url_set"] is True


def test_discord_is_registered_as_a_channel_everywhere():
    assert "discord" in NotificationChannel.values
    assert "discord" in NonEmailNotificationChannel.values
    # Present in the default table rather than relying on the False fallback.
    for feature in NotificationFeature.values:
        assert "discord" in DEFAULT_CHANNEL_STATE[feature]
        assert default_state(feature, "discord") is False


def test_discord_payload_uses_content_not_text(monkeypatch):
    """Discord ignores Slack's "text" key and 400s -- the bodies must differ."""
    from apps.integrations import webhooks

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        captured[req.full_url] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(webhooks.urllib_request, "urlopen", fake_urlopen)

    space = make_space("p10-payload")
    space.set_discord_webhook_url(DISCORD_WEBHOOK)
    space.set_slack_webhook_url(SLACK_WEBHOOK)
    space.save()

    webhooks.send_webhook(space, channel="discord", text="hello")
    webhooks.send_webhook(space, channel="slack", text="hello")
    assert captured[DISCORD_WEBHOOK] == {"content": "hello"}
    assert captured[SLACK_WEBHOOK] == {"text": "hello"}


def test_discord_messages_are_trimmed_to_the_provider_limit(monkeypatch):
    """Over 2000 characters Discord rejects outright, so a long alert would vanish."""
    from apps.integrations import webhooks

    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        webhooks.urllib_request,
        "urlopen",
        lambda req, timeout=None: (
            captured.update(json.loads(req.data.decode("utf-8"))),
            FakeResponse(),
        )[1],
    )
    space = space_with_discord("p10-trim")
    webhooks.send_webhook(space, channel="discord", text="x" * 2500)
    assert len(captured["content"]) == 2000


def test_an_unconfigured_discord_channel_fails_terminally_without_sending():
    space = make_space("p10-unconfigured")
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"discord"})
    space.save()
    [log] = dispatch_channel(
        makerspace=space,
        channel="discord",
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request_pending",
        text_body="hi",
        sync=True,
    )
    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_channel_not_configured"


# --- the module keys -------------------------------------------------------------


def test_each_channel_has_its_own_module_key():
    for channel in CHANNELS:
        assert channel in module_registry.MODULE_KEYS
    # Independently switchable: none of them requires another.
    for channel in CHANNELS:
        assert module_registry.BY_KEY[channel].requires_modules == ()


def test_channel_keys_are_not_core_and_not_default_on():
    for channel in CHANNELS:
        definition = module_registry.BY_KEY[channel]
        assert definition.is_core is False
        assert definition.default_enabled is False


def test_uninstalling_the_module_skips_the_send_and_keeps_the_credential():
    space = space_with_discord("p10-gate")
    space.enabled_modules = [
        key for key in space.enabled_modules if key != "discord"
    ]
    space.save()

    assert channel_module_blocks(space, "discord") is True
    [log] = dispatch_channel(
        makerspace=space,
        channel="discord",
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request_pending",
        text_body="hi",
        sync=True,
    )
    # Recorded, not dropped -- an operator can see what the toggle suppressed.
    assert log.status == NotificationDeliveryStatus.SKIPPED
    assert log.error == "notification_channel_module_disabled"
    # The webhook survives, so re-enabling needs no credential re-entry.
    space.refresh_from_db()
    assert space.get_discord_webhook_url() == DISCORD_WEBHOOK


def test_a_queued_row_is_skipped_when_the_module_goes_away_mid_flight():
    """A PENDING row can sit in Celery across an uninstall; the retry re-enters here."""
    from apps.integrations.dispatch_channels import _deliver_notification

    space = space_with_discord("p10-queued")
    log = NotificationDeliveryLog.objects.create(
        makerspace=space,
        channel="discord",
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request_pending",
        text_body="hi",
        status=NotificationDeliveryStatus.PENDING,
    )
    space.enabled_modules = [k for k in space.enabled_modules if k != "discord"]
    space.save()

    _deliver_notification(log)
    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.SKIPPED


def test_enabling_the_module_cannot_make_an_unconfigured_channel_send():
    """The key is an additive AND, never a replacement for the credential check."""
    space = make_space("p10-additive")
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"discord"})
    space.save()
    assert channel_module_blocks(space, "discord") is False
    [log] = dispatch_channel(
        makerspace=space,
        channel="discord",
        feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request_pending",
        text_body="hi",
        sync=True,
    )
    assert log.status == NotificationDeliveryStatus.FAILED


def test_one_channel_module_does_not_gate_another():
    space = make_space("p10-isolated")
    space.enabled_modules = sorted(
        (set(space.enabled_modules or []) | {"slack"}) - {"discord", "mattermost"}
    )
    space.save()
    assert channel_module_blocks(space, "slack") is False
    assert channel_module_blocks(space, "discord") is True
    assert channel_module_blocks(space, "mattermost") is True


def test_native_push_is_not_gated_by_a_module_key():
    """It is governed by the standalone `mobile.push` feature, not a module."""
    space = make_space("p10-push")
    space.enabled_modules = []
    space.save()
    assert channel_module_blocks(space, "native_push") is False


def test_the_matrix_omits_a_channel_whose_module_is_uninstalled():
    """Omitted, not rendered-disabled: a tickable column would store an inert preference."""
    from tests.return_helpers import make_member
    from tests.test_notification_rules_api import authenticated_client, rules_url

    space = space_with_discord("p10-matrix")
    manager = make_member("p10-matrix-mgr", space)

    body = authenticated_client(manager).get(rules_url(space)).data
    assert "discord" in [channel["key"] for channel in body["channels"]]

    space.enabled_modules = [k for k in space.enabled_modules if k != "discord"]
    space.save()
    body = authenticated_client(manager).get(rules_url(space)).data
    keys = [channel["key"] for channel in body["channels"]]
    assert "discord" not in keys
    # A neighbouring channel still resolves -- filtering in place is where an off-by-one
    # removes too much.
    assert "slack" in keys
    # No orphan preference cells for a column that no longer exists.
    assert all(cell["channel"] != "discord" for cell in body["preferences"])


def test_a_skip_counts_as_neither_delivered_nor_failed():
    """`bool(delivered_counts)` must not read a suppressed channel as a sent message."""
    from apps.integrations.notify import _run_guarded
    from apps.integrations.notification_catalog import is_notification_enabled
    from apps.integrations.models import NotificationPreference

    space = space_with_discord("p10-counts")
    NotificationPreference.objects.create(
        makerspace=space,
        feature=NotificationFeature.HARDWARE_REQUESTS,
        channel="discord",
        enabled=True,
    )
    assert is_notification_enabled(space, NotificationFeature.HARDWARE_REQUESTS, "discord")
    space.enabled_modules = [k for k in space.enabled_modules if k != "discord"]
    space.save()

    from apps.integrations.notify import LifecyclePayload

    result = _run_guarded(
        space,
        NotificationFeature.HARDWARE_REQUESTS,
        "request_pending",
        lambda: LifecyclePayload(text="hi"),
        True,
    )
    assert result.delivered_counts.get("discord") is None
    assert result.failed_counts.get("discord") is None
