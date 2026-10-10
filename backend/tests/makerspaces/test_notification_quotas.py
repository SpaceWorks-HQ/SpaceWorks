"""The remaining BU notification channels enforce per-tenant daily send caps.

Use real dispatch, credential checks and counters; stub only the outbound transports.
Webhook gets an explicit override, leaving the unresolved default-limit product call alone.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.dispatch_destination import deliver_text_to_destination
from apps.integrations.models import (
    DailyNotificationCounter, NotificationDeliveryStatus, NotificationDestination,
    NotificationFeature, PlatformPushSettings,
)
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db
CHANNELS = ("discord", "native_push", "webhook")


@pytest.fixture
def transports(monkeypatch):
    sent = []

    def webhook(url, payload, extra_headers=None):
        sent.append("webhook" if extra_headers else "discord")

    def push(log):
        sent.append(log.channel)
        return True

    monkeypatch.setattr("apps.integrations.webhooks._deliver", webhook)
    monkeypatch.setattr("apps.integrations.push.deliver_native_push", push)
    return sent


def configured_space(slug, channel):
    space = make_space(slug)
    space.resource_limit_overrides = {channel: 1}
    space.save(update_fields=["resource_limit_overrides"])
    if channel == "native_push":
        platform = PlatformPushSettings.load()
        platform.set_fcm_service_account('{"configured": true}')
        platform.save()
        return space, None
    destination = NotificationDestination(
        makerspace=space, channel=channel, label="Room A"
    )
    destination.set_webhook_url("https://hooks.example.org/room")
    if channel == "webhook":
        destination.set_signing_secret("notification-quota-signing-secret")
    destination.save()
    return space, destination


def dispatch(space, channel):
    return dispatch_channel(
        makerspace=space, channel=channel, feature=NotificationFeature.HARDWARE_REQUESTS,
        event="request.accepted", text_body="Request accepted", sync=True,
    )


@pytest.mark.parametrize("channel", CHANNELS)
def test_managed_notification_cap_blocks_transport_and_preserves_counter(
    settings, transports, channel,
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, _ = configured_space(f"notification-quota-{channel}", channel)

    [first] = dispatch(space, channel)
    [second] = dispatch(space, channel)

    assert first.status == NotificationDeliveryStatus.SENT
    assert second.status == NotificationDeliveryStatus.FAILED
    assert second.error == f"Daily {channel} notification limit reached for this space."
    assert second.attempts == 0
    assert transports == [channel]
    counter = DailyNotificationCounter.objects.get(makerspace=space, channel=channel)
    assert counter.day == timezone.now().date()
    assert counter.count == 1


@pytest.mark.parametrize("channel", CHANNELS)
def test_self_host_notification_delivery_does_not_consume_managed_quota(
    settings, transports, channel,
):
    settings.PLATFORM_DOMAIN_SUFFIX = ""
    space, _ = configured_space(f"notification-quota-self-{channel}", channel)

    logs = [dispatch(space, channel)[0] for _ in range(2)]

    assert [log.status for log in logs] == [NotificationDeliveryStatus.SENT] * 2
    assert transports == [channel, channel]
    assert not DailyNotificationCounter.objects.filter(makerspace=space).exists()


@pytest.mark.parametrize("channel", CHANNELS)
def test_notification_caps_reset_daily_and_are_separate_for_each_tenant(
    settings, transports, channel,
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, _ = configured_space(f"notification-quota-day-{channel}", channel)
    other, _ = configured_space(f"notification-quota-other-{channel}", channel)
    yesterday = timezone.now().date() - timedelta(days=1)
    old = DailyNotificationCounter.objects.create(
        makerspace=space, channel=channel, day=yesterday, count=1,
    )

    assert dispatch(space, channel)[0].status == NotificationDeliveryStatus.SENT
    assert dispatch(other, channel)[0].status == NotificationDeliveryStatus.SENT
    assert dispatch(space, channel)[0].status == NotificationDeliveryStatus.FAILED
    old.refresh_from_db()
    assert old.count == 1
    assert DailyNotificationCounter.objects.get(
        makerspace=other, channel=channel, day=timezone.now().date()
    ).count == 1
    assert transports == [channel, channel]


@pytest.mark.parametrize("channel", ("discord", "webhook"))
def test_fanout_charges_each_room_and_shares_the_cap_with_explicit_delivery(
    settings, transports, channel,
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, first_room = configured_space(f"notification-quota-rooms-{channel}", channel)
    second_room = NotificationDestination(makerspace=space, channel=channel, label="Room B")
    second_room.set_webhook_url("https://hooks.example.org/other-room")
    if channel == "webhook":
        second_room.set_signing_secret("notification-quota-other-secret")
    second_room.save()

    logs = dispatch(space, channel)
    assert [log.status for log in logs] == [
        NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.FAILED,
    ]
    assert [log.destination_id for log in logs] == [first_room.pk, second_room.pk]
    result = deliver_text_to_destination(
        space, first_room, text="Scheduled report", feature="hardware_requests",
        event="report.ready", reference="quota-report",
    )
    assert result == (False, "notification_quota_exceeded")
    assert transports == [channel]
    assert DailyNotificationCounter.objects.get(makerspace=space, channel=channel).count == 1


@pytest.mark.parametrize("channel", ("discord", "webhook"))
def test_explicit_delivery_reserves_quota_before_lifecycle_dispatch(
    settings, transports, channel,
):
    settings.PLATFORM_DOMAIN_SUFFIX = ".space-works.tech"
    space, room = configured_space(f"notification-quota-report-{channel}", channel)

    assert deliver_text_to_destination(
        space, room, text="Scheduled report", feature="hardware_requests",
        event="report.ready", reference="quota-report",
    ) == (True, "")
    assert dispatch(space, channel)[0].status == NotificationDeliveryStatus.FAILED
    assert transports == [channel]
    assert DailyNotificationCounter.objects.get(makerspace=space, channel=channel).count == 1
