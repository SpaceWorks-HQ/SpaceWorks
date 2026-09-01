import logging
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.models import (
    DailyEmailCounter,
    DailyNotificationCounter,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
    NotificationFeature,
    NotificationPreference,
)
from apps.integrations.tasks import (
    _claim_notification_log,
    _should_retry_notification,
    deliver_notification_task,
)
from apps.integrations.webhooks import WebhookDeliveryError, send_webhook
from apps.makerspaces import limits
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db

SLACK_URL = "https://hooks.slack.test/services/T/B/secret"
MATTERMOST_URL = "https://mattermost.test/hooks/secret"


def configure(space, channel):
    if channel == "telegram":
        space.set_telegram_bot_token("telegram-secret-token")
        space.telegram_group_chat_id = "-100123"
        fields = ["telegram_bot_token", "telegram_group_chat_id"]
    elif channel == "slack":
        space.set_slack_webhook_url(SLACK_URL)
        fields = ["slack_webhook_url"]
    else:
        space.set_mattermost_webhook_url(MATTERMOST_URL)
        fields = ["mattermost_webhook_url"]
    space.save(update_fields=fields)
    return space


def dispatch(space, channel="slack", **kwargs):
    """The single log for a space with no destination rows.

    `dispatch_channel` fans out to one row per room; these tests all exercise the legacy
    makerspace-column path, which resolves to exactly one target, so unwrapping here keeps
    every assertion below about the thing it was written to check.
    """
    logs = dispatch_all(space, channel, **kwargs)
    assert len(logs) == 1
    return logs[0]


def dispatch_all(space, channel="slack", **kwargs):
    return dispatch_channel(
        makerspace=space,
        channel=channel,
        feature=NotificationFeature.BOOKINGS,
        event="booking_confirmed",
        text_body="Booking confirmed.",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("channel", "url"),
    [("slack", SLACK_URL), ("mattermost", MATTERMOST_URL)],
)
def test_send_webhook_posts_exact_json(channel, url, monkeypatch):
    space = configure(make_space(f"webhook-{channel}"), channel)
    target = object()
    resolver = Mock(return_value=target)
    post = Mock(return_value=(204, None))
    monkeypatch.setattr("apps.integrations.webhooks.resolve_webhook_target", resolver)
    monkeypatch.setattr("apps.integrations.webhooks._post_to_target", post)

    assert send_webhook(space, channel=channel, text="Hello ✓") is True

    resolver.assert_called_once_with(url)
    post.assert_called_once_with(target, b'{"text": "Hello \\u2713"}')


@pytest.mark.parametrize(
    "failure",
    [503, TimeoutError("timeout"), OSError("network")],
)
def test_send_webhook_wraps_transport_failures(failure, monkeypatch):
    space = configure(make_space(f"webhook-fail-{type(failure).__name__}"), "slack")
    monkeypatch.setattr(
        "apps.integrations.webhooks.resolve_webhook_target", Mock(return_value=object())
    )
    if isinstance(failure, int):
        post = Mock(return_value=(failure, None))
    else:
        post = Mock(side_effect=failure)
    monkeypatch.setattr("apps.integrations.webhooks._post_to_target", post)

    with pytest.raises(WebhookDeliveryError, match="Webhook delivery failed"):
        send_webhook(space, channel="slack", text="Hello")


def test_send_webhook_blank_and_malformed_secrets(monkeypatch):
    blank = make_space("webhook-blank")
    post = Mock()
    monkeypatch.setattr("apps.integrations.webhooks._post_to_target", post)
    assert send_webhook(blank, channel="slack", text="Hello") is False
    post.assert_not_called()

    malformed = make_space("webhook-malformed")
    malformed.set_slack_webhook_url("not-a-url")
    malformed.save(update_fields=["slack_webhook_url"])
    with pytest.raises(WebhookDeliveryError):
        send_webhook(malformed, channel="slack", text="Hello")
    post.assert_not_called()


def test_unconfigured_dispatch_fails_without_send_or_quota(monkeypatch):
    space = make_space("dispatch-unconfigured")
    NotificationPreference.objects.create(
        makerspace=space,
        feature=NotificationFeature.BOOKINGS,
        channel="slack",
        enabled=True,
    )
    sender = Mock()
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", sender)

    log = dispatch(space, sync=True)

    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_channel_not_configured"
    assert log.attempts == 0
    sender.assert_not_called()
    assert not DailyNotificationCounter.objects.exists()


def test_configured_sync_success_and_sender_failure(monkeypatch):
    space = configure(make_space("dispatch-sync"), "slack")
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    sender = Mock(return_value=True)
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", sender)
    sent = dispatch(space, sync=True)
    assert (sent.status, sent.attempts) == (NotificationDeliveryStatus.SENT, 1)
    assert sent.sent_at is not None

    sender.side_effect = ConnectionError("provider body must not persist")
    failed = dispatch(space, sync=True)
    assert failed.status == NotificationDeliveryStatus.FAILED
    assert failed.error == "notification_delivery_failed:ConnectionError"
    assert failed.attempts == 1


def test_telegram_payload_is_durable_and_passed_to_sender(monkeypatch):
    space = configure(make_space("dispatch-telegram"), "telegram")
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    sender = Mock(return_value=True)
    monkeypatch.setattr("apps.integrations.telegram.send_message", sender)
    # An arbitrary payload: the `payload` column carries delivery-time context (today,
    # the alert's `scope`, which push resolves its recipients from), and the property
    # under test is that it survives to the log row intact.
    payload = {"scope": {"kind": "machine", "id": 7}}

    log = dispatch(space, "telegram", payload=payload, sync=True)

    log.refresh_from_db()
    assert log.payload == payload
    assert log.status == NotificationDeliveryStatus.SENT
    # destination=None is the legacy makerspace-column path: this space has no rooms, so
    # the chat id still comes off the makerspace exactly as it did. No `reply_markup`:
    # the Telegram sender has no such parameter any more.
    sender.assert_called_once_with(space, "Booking confirmed.", destination=None)


def test_async_dispatch_enqueues_after_commit(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = configure(make_space("dispatch-async"), "slack")
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    delay = Mock()
    monkeypatch.setattr(deliver_notification_task, "delay", delay)

    with django_capture_on_commit_callbacks(execute=True):
        log = dispatch(space, sync=False)

    assert log.status == NotificationDeliveryStatus.PENDING
    delay.assert_called_once_with(log.pk)


def test_async_enqueue_failure_is_durable_and_does_not_raise(
    monkeypatch, django_capture_on_commit_callbacks
):
    space = configure(make_space("dispatch-enqueue-fail"), "slack")
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    monkeypatch.setattr(
        deliver_notification_task, "delay", Mock(side_effect=RuntimeError("broker down"))
    )

    with django_capture_on_commit_callbacks(execute=True):
        log = dispatch(space, sync=False)

    log.refresh_from_db()
    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_delivery_failed:RuntimeError"


def test_notification_claim_skips_active_and_reclaims_retryable_rows():
    space = make_space("notification-claims")
    base = dict(
        makerspace=space,
        channel="slack",
        feature=NotificationFeature.BOOKINGS,
        event="booking_confirmed",
        text_body="Body",
    )
    sent = NotificationDeliveryLog.objects.create(
        **base, status=NotificationDeliveryStatus.SENT
    )
    fresh = NotificationDeliveryLog.objects.create(
        **base, status=NotificationDeliveryStatus.SENDING
    )
    stale = NotificationDeliveryLog.objects.create(
        **base, status=NotificationDeliveryStatus.SENDING
    )
    failed = NotificationDeliveryLog.objects.create(
        **base, status=NotificationDeliveryStatus.FAILED, error="old"
    )
    NotificationDeliveryLog.objects.filter(pk=stale.pk).update(
        updated_at=timezone.now() - timedelta(minutes=5)
    )

    assert _claim_notification_log(sent.pk) is None
    assert _claim_notification_log(fresh.pk) is None
    assert _claim_notification_log(stale.pk).status == NotificationDeliveryStatus.SENDING
    retried = _claim_notification_log(failed.pk)
    assert retried.status == NotificationDeliveryStatus.SENDING
    assert retried.error == ""


def test_managed_channel_cap_blocks_second_send(monkeypatch):
    space = configure(make_space("notification-cap"), "slack")
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr(limits, "resource_limit", lambda makerspace, channel: 1)
    monkeypatch.setattr(
        "apps.integrations.webhooks.resolve_webhook_target", Mock(return_value=object())
    )
    post = Mock(return_value=(204, None))
    monkeypatch.setattr("apps.integrations.webhooks._post_to_target", post)

    first = dispatch(space, sync=True)
    second = dispatch(space, sync=True)

    assert first.status == NotificationDeliveryStatus.SENT
    assert second.status == NotificationDeliveryStatus.FAILED
    assert second.error == "Daily slack notification limit reached for this space."
    assert post.call_count == 1
    counter = DailyNotificationCounter.objects.get()
    assert (counter.channel, counter.count) == ("slack", 1)
    assert not DailyEmailCounter.objects.exists()


@pytest.mark.parametrize("unlimited", [None, -1])
def test_managed_null_and_minus_one_are_unlimited(unlimited, monkeypatch):
    space = configure(make_space(f"notification-unlimited-{unlimited}"), "slack")
    space.resource_limit_overrides = {"slack": unlimited}
    space.save(update_fields=["resource_limit_overrides"])
    monkeypatch.setattr(limits, "is_self_host", lambda: False)
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", Mock(return_value=True))

    assert [dispatch(space, sync=True).status for _ in range(2)] == [
        NotificationDeliveryStatus.SENT,
        NotificationDeliveryStatus.SENT,
    ]
    assert not DailyNotificationCounter.objects.exists()


def test_self_host_ignores_zero_cap_without_counter(monkeypatch):
    space = configure(make_space("notification-self-host"), "slack")
    space.resource_limit_overrides = {"slack": 0}
    space.save(update_fields=["resource_limit_overrides"])
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", Mock(return_value=True))

    assert dispatch(space, sync=True).status == NotificationDeliveryStatus.SENT
    assert not DailyNotificationCounter.objects.exists()


def test_telegram_global_token_fallback_is_configured(settings, monkeypatch):
    # A space with a group chat id but no per-space token, relying on the global
    # settings.TELEGRAM_BOT_TOKEN fallback (mirrored by telegram.send_message), must be
    # treated as configured — not silently recorded not-configured.
    settings.TELEGRAM_BOT_TOKEN = "global-fallback-token"
    space = make_space("telegram-global")
    space.telegram_group_chat_id = "-100999"
    space.save(update_fields=["telegram_group_chat_id"])
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    sender = Mock(return_value=True)
    monkeypatch.setattr("apps.integrations.telegram.send_message", sender)

    log = dispatch(space, channel="telegram", sync=True)

    assert log.status == NotificationDeliveryStatus.SENT
    sender.assert_called_once()


def test_undecryptable_secret_fails_terminally_without_raising(monkeypatch):
    # A rotated/missing API_CLIENT_ENC_KEY or corrupt ciphertext makes the decrypting
    # getter raise. dispatch_channel must NOT propagate — it records a terminal
    # not-configured failure, makes no send, and consumes no quota (review P2).
    space = configure(make_space("dispatch-badkey"), "slack")
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    monkeypatch.setattr(
        type(space),
        "get_slack_webhook_url",
        lambda self: (_ for _ in ()).throw(ValueError("bad Fernet key")),
    )
    sender = Mock()
    monkeypatch.setattr("apps.integrations.webhooks.send_webhook", sender)

    log = dispatch(space, sync=True)

    assert log.status == NotificationDeliveryStatus.FAILED
    assert log.error == "notification_channel_not_configured"
    sender.assert_not_called()
    assert not DailyNotificationCounter.objects.exists()


def test_only_delivery_failures_are_retried():
    # Provider-delivery failures retry; a delivery-time not-configured row is terminal.
    space = make_space("retry-predicate")
    base = dict(
        makerspace=space,
        channel="slack",
        feature=NotificationFeature.BOOKINGS,
        event="booking_confirmed",
        text_body="Body",
        status=NotificationDeliveryStatus.FAILED,
    )
    delivery_failed = NotificationDeliveryLog.objects.create(
        **base, error="notification_delivery_failed:ConnectionError"
    )
    not_configured = NotificationDeliveryLog.objects.create(
        **base, error="notification_channel_not_configured"
    )
    sent = NotificationDeliveryLog.objects.create(
        makerspace=space,
        channel="slack",
        feature=NotificationFeature.BOOKINGS,
        event="booking_confirmed",
        text_body="Body",
        status=NotificationDeliveryStatus.SENT,
    )

    assert _should_retry_notification(delivery_failed) is True
    assert _should_retry_notification(not_configured) is False
    assert _should_retry_notification(sent) is False


def test_failures_never_log_or_persist_destination_secrets(monkeypatch, caplog):
    sentinel_url = "https://sentinel.invalid/hooks/DO-NOT-LOG"
    sentinel_token = "telegram-token-DO-NOT-LOG"
    space = make_space("notification-no-secret")
    space.set_slack_webhook_url(sentinel_url)
    space.set_telegram_bot_token(sentinel_token)
    space.telegram_group_chat_id = "-100secret"
    space.save()
    monkeypatch.setattr(limits, "is_self_host", lambda: True)
    monkeypatch.setattr(
        "apps.integrations.webhooks.send_webhook",
        Mock(side_effect=RuntimeError(f"failed for {sentinel_url} {sentinel_token}")),
    )

    with caplog.at_level(logging.ERROR, logger="apps.integrations.dispatch_channels"):
        log = dispatch(space, sync=True)

    log.refresh_from_db()
    assert log.error == "notification_delivery_failed:RuntimeError"
    stored = " ".join(
        str(getattr(log, field))
        for field in ("channel", "feature", "event", "text_body", "payload", "error")
    )
    records = caplog.text + " ".join(repr(record.__dict__) for record in caplog.records)
    assert sentinel_url not in stored + records
    assert sentinel_token not in stored + records
