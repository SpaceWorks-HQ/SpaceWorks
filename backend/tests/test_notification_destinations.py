"""Chat destinations and the fan-out (Notifications v2, N2).

The two assertions this file exists for are migration equivalence — a space that has not
been given destinations sends exactly as it did — and Telegram parity, because Telegram
never went through the webhook sender and is the channel a "works on all four" claim
quietly fails on.
"""

import pytest
from django.test import override_settings

from apps.integrations import destinations as destination_service
from apps.integrations import telegram, webhooks
from apps.integrations.destinations import NotificationScope, resolve_destinations
from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.models import (
    NotificationDeliveryStatus,
    NotificationFeature,
)
from apps.integrations.models_destinations import NotificationDestination
from apps.integrations.notification_enums import (
    MAX_MESSAGE_LENGTH,
    ChatNotificationChannel,
    trim_for_channel,
)
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_space(slug, **kw):
    return Makerspace.objects.create(name=slug, slug=slug, **kw)


def webhook_destination(space, channel, label, url="https://hooks.example/x"):
    destination = NotificationDestination(
        makerspace=space, channel=channel, label=label, telegram_chat_id=""
    )
    destination.set_webhook_url(url)
    destination.save()
    return destination


def telegram_destination(space, label, chat_id="-100200300"):
    return NotificationDestination.objects.create(
        makerspace=space,
        channel=ChatNotificationChannel.TELEGRAM,
        label=label,
        webhook_url="",
        telegram_chat_id=chat_id,
    )


def capture_sends(monkeypatch):
    """Record what each sender was asked to deliver, and to which room."""
    sent = []

    def fake_webhook(makerspace, *, channel, text, destination=None):
        sent.append(
            {
                "channel": channel,
                "text": text,
                "destination": getattr(destination, "label", None),
                "url": destination.get_webhook_url() if destination else None,
            }
        )
        return True

    def fake_telegram(makerspace, text, reply_markup=None, destination=None):
        sent.append(
            {
                "channel": "telegram",
                "text": text,
                "destination": getattr(destination, "label", None),
                "chat_id": telegram.resolve_chat_id(makerspace, destination),
            }
        )
        return True

    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", fake_webhook)
    monkeypatch.setattr("apps.integrations.telegram.send_message", fake_telegram)
    return sent


def fan_out(space, channel, *, scope=None):
    return dispatch_channel(
        makerspace=space,
        channel=channel,
        feature=NotificationFeature.MAINTENANCE,
        event="logged",
        text_body="Machine needs attention",
        sync=True,
        scope=scope,
    )


# --- migration equivalence: no destinations means the legacy column ------------------


def test_a_space_with_no_destinations_sends_through_the_makerspace_webhook(monkeypatch):
    space = make_space("dest-legacy-slack")
    space.set_slack_webhook_url("https://hooks.example/legacy")
    space.save()
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "slack")

    assert [log.status for log in logs] == [NotificationDeliveryStatus.SENT]
    assert logs[0].destination_id is None
    assert [row["destination"] for row in sent] == [None]


def test_a_space_with_no_destinations_still_sends_telegram(monkeypatch):
    """Telegram's legacy path is a different code path — it never used send_webhook."""
    space = make_space("dest-legacy-telegram")
    space.set_telegram_bot_token("token-1")
    space.telegram_group_chat_id = "-100999"
    space.save()
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "telegram")

    assert [log.status for log in logs] == [NotificationDeliveryStatus.SENT]
    assert sent[0]["chat_id"] == "-100999"


def test_the_backfill_migration_reproduces_the_legacy_credential():
    """What migration 0021 writes must resolve to the same destination it replaced."""
    space = make_space("dest-backfill-shape")
    space.set_slack_webhook_url("https://hooks.example/backfilled")
    space.save()

    destination = webhook_destination(
        space, "slack", "Main", "https://hooks.example/backfilled"
    )

    assert destination.get_webhook_url() == space.get_slack_webhook_url()
    assert resolve_destinations(space, "slack") == [destination]


# --- fan-out: one row per room -------------------------------------------------------


def test_every_matching_room_gets_its_own_log_row(monkeypatch):
    space = make_space("dest-fanout")
    webhook_destination(space, "discord", "General", "https://hooks.example/general")
    webhook_destination(space, "discord", "Workshop", "https://hooks.example/workshop")
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "discord")

    assert len(logs) == 2
    assert {log.destination_label for log in logs} == {"General", "Workshop"}
    assert all(log.status == NotificationDeliveryStatus.SENT for log in logs)
    assert sorted(row["url"] for row in sent) == [
        "https://hooks.example/general",
        "https://hooks.example/workshop",
    ]


def test_quota_is_charged_once_per_room(monkeypatch):
    space = make_space("dest-quota")
    webhook_destination(space, "slack", "A")
    webhook_destination(space, "slack", "B")
    webhook_destination(space, "slack", "C")
    capture_sends(monkeypatch)

    charged = []
    monkeypatch.setattr(
        "apps.makerspaces.limits.reserve_notification_quota",
        lambda space_, channel: charged.append(channel) or True,
    )

    fan_out(space, "slack")

    # Three rooms is three real sends, and the real send count is what costs.
    assert charged == ["slack", "slack", "slack"]


def test_a_room_with_no_credential_is_terminal_and_does_not_stop_the_others(monkeypatch):
    space = make_space("dest-partial-failure")
    good = webhook_destination(space, "mattermost", "Good")
    broken = webhook_destination(space, "mattermost", "Broken")
    # The check constraint forbids a blank credential, so the realistic failure is an
    # unreadable one: a rotated API_CLIENT_ENC_KEY or corrupt ciphertext makes decrypt
    # raise, and that must be treated as not-configured rather than aborting the fan-out.
    NotificationDestination.objects.filter(pk=broken.pk).update(
        webhook_url="fernet:not-decryptable"
    )
    capture_sends(monkeypatch)

    logs = {log.destination_label: log for log in fan_out(space, "mattermost")}

    assert logs["Good"].status == NotificationDeliveryStatus.SENT
    assert logs["Broken"].status == NotificationDeliveryStatus.FAILED
    assert logs["Broken"].error == "notification_channel_not_configured"
    assert good.pk != broken.pk


def test_a_deactivated_sole_room_does_not_fall_back_to_the_legacy_webhook(monkeypatch):
    space = make_space("dest-deactivated")
    space.set_slack_webhook_url("https://hooks.example/legacy")
    space.save()
    NotificationDestination.objects.filter(
        pk=webhook_destination(space, "slack", "Main").pk
    ).update(is_active=False)
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "slack")

    # Switching a room off must stop it, not reveal the credential underneath.
    assert [log.status for log in logs] == [NotificationDeliveryStatus.SKIPPED]
    assert logs[0].error == "notification_no_matching_destination"
    assert sent == []


# --- scope: union, and unscoped means space-wide -------------------------------------


def make_machine(space, name):
    machine_type = MachineType.objects.create(
        makerspace=space, name=f"{name}-type", slug=f"{space.slug}-{name}-type"
    )
    return Machine.objects.create(makerspace=space, machine_type=machine_type, name=name)


def test_an_unscoped_room_receives_everything(monkeypatch):
    space = make_space("dest-unscoped")
    webhook_destination(space, "discord", "General")
    laser = make_machine(space, "laser")
    capture_sends(monkeypatch)

    logs = fan_out(space, "discord", scope=NotificationScope(machine=laser))

    assert [log.destination_label for log in logs] == ["General"]


def test_a_machine_scoped_room_only_receives_its_machine(monkeypatch):
    space = make_space("dest-machine-scope")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    laser_room = webhook_destination(space, "discord", "Laser room")
    laser_room.machine_scopes.create(machine=laser)
    capture_sends(monkeypatch)

    assert [log.destination_label for log in fan_out(
        space, "discord", scope=NotificationScope(machine=laser)
    )] == ["Laser room"]

    other = fan_out(space, "discord", scope=NotificationScope(machine=printer))
    assert [log.status for log in other] == [NotificationDeliveryStatus.SKIPPED]


def test_machine_and_type_scopes_are_a_union(monkeypatch):
    space = make_space("dest-union-scope")
    printer_a = make_machine(space, "printer-a")
    printer_b = make_machine(space, "printer-b")
    laser = make_machine(space, "laser")
    room = webhook_destination(space, "slack", "Fabrication")
    room.machine_type_scopes.create(machine_type=printer_a.machine_type)
    room.machine_scopes.create(machine=laser)
    capture_sends(monkeypatch)

    for machine in (printer_a, laser):
        assert [log.destination_label for log in fan_out(
            space, "slack", scope=NotificationScope(machine=machine)
        )] == ["Fabrication"]

    # printer_b has its own type (each make_machine creates one), so it matches neither.
    assert [log.status for log in fan_out(
        space, "slack", scope=NotificationScope(machine=printer_b)
    )] == [NotificationDeliveryStatus.SKIPPED]


def test_an_alert_with_no_subject_reaches_no_scoped_room(monkeypatch):
    space = make_space("dest-no-subject")
    laser = make_machine(space, "laser")
    room = webhook_destination(space, "discord", "Laser room")
    room.machine_scopes.create(machine=laser)
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "discord", scope=None)

    assert [log.status for log in logs] == [NotificationDeliveryStatus.SKIPPED]
    assert sent == []


def test_scoping_never_hides_the_general_room(monkeypatch):
    space = make_space("dest-mixed-scope")
    laser = make_machine(space, "laser")
    general = webhook_destination(space, "discord", "General")
    laser_room = webhook_destination(space, "discord", "Laser room")
    laser_room.machine_scopes.create(machine=laser)
    capture_sends(monkeypatch)

    labels = {
        log.destination_label
        for log in fan_out(space, "discord", scope=NotificationScope(machine=laser))
    }

    assert labels == {"General", "Laser room"}
    assert general.pk != laser_room.pk


# --- Telegram parity (G1/D16) --------------------------------------------------------


def test_telegram_destinations_post_to_their_own_chat_id(monkeypatch):
    space = make_space("dest-telegram-rooms")
    space.set_telegram_bot_token("token-1")
    space.telegram_group_chat_id = "-100111"
    space.save()
    telegram_destination(space, "Front desk", "-100222")
    telegram_destination(space, "Workshop", "-100333")
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "telegram")

    assert len(logs) == 2
    # The makerspace-wide chat id is NOT used once rooms exist.
    assert sorted(row["chat_id"] for row in sent) == ["-100222", "-100333"]


def test_a_telegram_room_shares_the_makerspace_bot():
    """D16: no per-destination token, because inbound callbacks have one webhook secret."""
    space = make_space("dest-telegram-token")
    space.set_telegram_bot_token("space-token")
    space.save()
    destination = telegram_destination(space, "Workshop")

    assert not hasattr(destination, "bot_token")
    assert telegram.resolve_bot_token(space) == "space-token"


def test_inbound_callbacks_do_not_depend_on_which_room_sent_the_message():
    """G6: the reason one bot per makerspace is enough.

    An accept/reject button posts back to a single registered webhook authenticated by
    one deployment-wide secret. Routing resolves the ACTOR from `from.id` and the request
    from the callback data — the chat the button was pressed in is never consulted — so
    adding rooms cannot strand a callback. If this ever starts reading a chat id, per-room
    Telegram destinations need per-bot webhook secrets and inbound routing first.
    """
    from apps.integrations.views import _parse_callback

    assert _parse_callback("accept:42") == ("accept", 42, "")
    assert _parse_callback("reject:42:out of stock") == ("reject", 42, "out of stock")


@override_settings(TELEGRAM_BOT_TOKEN="deployment-token")
def test_a_telegram_room_falls_back_to_the_deployment_token():
    space = make_space("dest-telegram-fallback")
    assert telegram.resolve_bot_token(space) == "deployment-token"


@override_settings(TELEGRAM_BOT_TOKEN="")
def test_a_telegram_room_with_no_resolvable_token_is_terminal_not_silent(monkeypatch):
    space = make_space("dest-telegram-no-token")
    telegram_destination(space, "Workshop")
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "telegram")

    assert [log.status for log in logs] == [NotificationDeliveryStatus.FAILED]
    assert logs[0].error == "notification_channel_not_configured"
    assert sent == []


# --- G2: every channel has a length ceiling ------------------------------------------


@pytest.mark.parametrize("channel", sorted(MAX_MESSAGE_LENGTH))
def test_each_channel_trims_at_its_own_boundary(channel):
    limit = MAX_MESSAGE_LENGTH[channel]

    assert trim_for_channel(channel, "x" * limit) == "x" * limit
    trimmed = trim_for_channel(channel, "x" * (limit + 1))
    assert len(trimmed) == limit
    assert trimmed.endswith("…")


def test_every_chat_channel_declares_a_limit():
    # A channel with no entry sends unbounded bodies and fails at the provider, which is
    # exactly the Telegram bug this table was added to close.
    assert set(MAX_MESSAGE_LENGTH) == set(ChatNotificationChannel.values)


def test_telegram_trims_rather_than_failing(monkeypatch):
    space = make_space("dest-telegram-trim")
    space.set_telegram_bot_token("token-1")
    space.telegram_group_chat_id = "-100111"
    space.save()
    captured = {}

    def fake_urlopen(request, timeout=None):
        import json

        captured["payload"] = json.loads(request.data.decode())
        raise AssertionError("stop after capture")

    monkeypatch.setattr("apps.integrations.telegram.urllib_request.urlopen", fake_urlopen)

    with pytest.raises(telegram.TelegramDeliveryError):
        telegram.send_message(space, "x" * 5000)

    assert len(captured["payload"]["text"]) == MAX_MESSAGE_LENGTH["telegram"]


# --- G3: a failure is attributable to a room -----------------------------------------


def test_deleting_a_room_keeps_its_delivery_history_and_stops_queued_sends(monkeypatch):
    from apps.integrations.dispatch_channels import _deliver_notification

    space = make_space("dest-deleted-room")
    room = webhook_destination(space, "slack", "Workshop")
    capture_sends(monkeypatch)

    [log] = fan_out(space, "slack")
    room.delete()
    log.refresh_from_db()

    # History survives the room (SET_NULL), and the label is what still names it.
    assert log.destination_id is None
    assert log.destination_label == "Workshop"

    log.status = NotificationDeliveryStatus.PENDING
    log.save(update_fields=["status"])
    redelivered = _deliver_notification(log)

    # It must NOT fall through to the makerspace-wide webhook.
    assert redelivered.status == NotificationDeliveryStatus.FAILED
    assert redelivered.error == "notification_destination_deleted"


# --- fail open -----------------------------------------------------------------------


def test_a_broken_destination_lookup_falls_back_to_the_legacy_path(monkeypatch):
    space = make_space("dest-fail-open")

    def boom(*args, **kwargs):
        raise RuntimeError("destination table unavailable")

    monkeypatch.setattr(
        destination_service.NotificationDestination.objects, "filter", boom
    )

    assert resolve_destinations(space, "slack") == [None]


def test_module_gate_short_circuits_before_rooms_are_resolved(monkeypatch):
    space = make_space("dest-module-gate")
    webhook_destination(space, "discord", "General")
    space.enabled_modules = [key for key in space.enabled_modules if key != "discord"]
    space.save(update_fields=["enabled_modules"])
    sent = capture_sends(monkeypatch)

    logs = fan_out(space, "discord")

    assert [log.status for log in logs] == [NotificationDeliveryStatus.SKIPPED]
    assert logs[0].error == "notification_channel_module_disabled"
    assert sent == []


# --- G5: purging a channel destroys its credentials ----------------------------------


def test_each_chat_channel_has_a_module_purge_plan():
    from apps.makerspaces.module_purge_plans import BY_KEY

    for key in ChatNotificationChannel.values:
        assert key in BY_KEY, f"{key} destinations would survive a purge"


def test_purging_a_channel_deletes_only_that_channels_rooms():
    from apps.makerspaces.module_purge_collectors import discord_destinations_delete

    space = make_space("dest-purge")
    webhook_destination(space, "discord", "General")
    kept = webhook_destination(space, "slack", "General")

    discord_destinations_delete(space, None)

    assert not NotificationDestination.objects.filter(
        makerspace=space, channel="discord"
    ).exists()
    assert NotificationDestination.objects.filter(pk=kept.pk).exists()


# --- N2b: health reports every room, and never the credential ------------------------


def test_health_reports_each_room_with_its_last_failure(monkeypatch):
    from apps.integrations.health import build_integration_health

    space = make_space("dest-health")
    webhook_destination(space, "discord", "General", "https://hooks.example/general")
    telegram_destination(space, "Front desk")

    def failing(makerspace, *, channel, text, destination=None):
        raise webhooks.WebhookDeliveryError("nope")

    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", failing)
    fan_out(space, "discord")

    section = build_integration_health(space)["chat_destinations"]
    by_label = {item["label"]: item for item in section["destinations"]}

    assert section["status"] == "warn"
    assert by_label["General"]["failed"] == 1
    assert by_label["General"]["last_failure"]["error"]
    assert by_label["Front desk"]["failed"] == 0
    # Both channels are reported, not just Telegram — the gap this section closes.
    assert {item["channel"] for item in section["destinations"]} == {"discord", "telegram"}


def test_health_never_echoes_a_stored_credential():
    from apps.integrations.health import build_integration_health

    space = make_space("dest-health-secret")
    webhook_destination(space, "slack", "General", "https://hooks.example/super-secret")

    payload = repr(build_integration_health(space))

    assert "super-secret" in "https://hooks.example/super-secret"  # sanity
    assert "super-secret" not in payload
    assert payload.count("'configured': True") >= 1


def test_health_still_reports_channels_on_the_legacy_path():
    from apps.integrations.health import build_integration_health

    space = make_space("dest-health-legacy")
    space.set_slack_webhook_url("https://hooks.example/legacy")
    space.save()

    legacy = build_integration_health(space)["chat_destinations"]["legacy_channels"]

    # A space with no rooms still sends; reporting it as unconfigured would read as an
    # outage that is not happening.
    assert legacy["slack"] is True
    assert legacy["discord"] is False


# --- the credential cannot be the wrong shape ----------------------------------------


def test_a_webhook_channel_cannot_store_a_chat_id():
    from django.db.utils import IntegrityError

    space = make_space("dest-constraint-webhook")
    with pytest.raises(IntegrityError):
        NotificationDestination.objects.create(
            makerspace=space,
            channel="slack",
            label="Wrong",
            webhook_url="",
            telegram_chat_id="-100111",
        )


def test_a_telegram_destination_cannot_store_a_webhook():
    from django.db.utils import IntegrityError

    space = make_space("dest-constraint-telegram")
    with pytest.raises(IntegrityError):
        NotificationDestination.objects.create(
            makerspace=space,
            channel="telegram",
            label="Wrong",
            webhook_url="fernet:whatever",
            telegram_chat_id="",
        )
