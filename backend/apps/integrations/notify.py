"""Fail-safe lifecycle notification fan-out."""

import logging
from dataclasses import dataclass, field

from django.db import transaction

from apps.integrations import notification_rules
from apps.integrations.dispatch import dispatch_email
from apps.integrations.dispatch_channels import dispatch_channel
from apps.integrations.models import (
    EmailLog,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationFeature,
)
from apps.integrations.notification_catalog import FEATURE_EVENTS, is_notification_enabled

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailDelivery:
    to_email: str
    subject: str
    text_body: str
    html_body: str = ""
    audience: str = "staff"
    target: str = ""
    stream: str = ""
    mute_event: str = ""
    persist_body: bool = True


@dataclass(frozen=True)
class LifecyclePayload:
    text: str
    emails: tuple[EmailDelivery, ...] = ()
    telegram_reply_markup: dict | None = None


@dataclass(frozen=True)
class NotificationResult:
    scheduled: bool
    delivered_counts: dict[str, int] = field(default_factory=dict)
    failed_counts: dict[str, int] = field(default_factory=dict)


def _increment(counts, channel):
    try:
        counts[channel] = counts.get(channel, 0) + 1
    except Exception:
        pass


def _email_muted(makerspace, delivery):
    if not delivery.stream or not delivery.mute_event:
        return False
    if delivery.audience == "requester" or delivery.target == "requester":
        return notification_rules.is_requester_muted(
            makerspace, delivery.stream, delivery.mute_event
        )
    if delivery.audience == "staff" and delivery.target:
        return notification_rules.role_muted(
            makerspace, delivery.stream, delivery.mute_event, delivery.target
        )
    return False


def _dispatch_email_delivery(makerspace, feature_event, delivery, sync, delivered, failed):
    if _email_muted(makerspace, delivery):
        return
    try:
        log = dispatch_email(
            makerspace=makerspace,
            to_email=delivery.to_email,
            subject=delivery.subject,
            text_body=delivery.text_body,
            html_body=delivery.html_body,
            stream=delivery.stream,
            event=delivery.mute_event or feature_event,
            audience=delivery.audience,
            persist_body=delivery.persist_body,
            sync=sync,
        )
    except Exception:
        _increment(failed, NotificationChannel.EMAIL)
        logger.warning(
            "lifecycle_email_dispatch_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None)},
        )
        return
    if log.status == EmailLog.Status.SKIPPED:
        # Neither delivered nor failed: the makerspace turned email off, so counting it
        # either way misreports the lifecycle result (`notify_return_due` returns
        # `bool(delivered_counts)`, and a skip must not read as a sent reminder).
        return
    target = failed if log.status == EmailLog.Status.FAILED else delivered
    _increment(target, NotificationChannel.EMAIL)


def _run_guarded(makerspace, feature, event, build, sync):
    delivered, failed = {}, {}
    try:
        payload = build()
        enabled = {
            channel: is_notification_enabled(makerspace, feature, channel)
            for channel in NotificationChannel.values
        }
        if enabled[NotificationChannel.EMAIL]:
            for delivery in payload.emails:
                _dispatch_email_delivery(makerspace, event, delivery, sync, delivered, failed)
        for channel in (
            NotificationChannel.TELEGRAM,
            NotificationChannel.SLACK,
            NotificationChannel.MATTERMOST,
            NotificationChannel.DISCORD,
            NotificationChannel.NATIVE_PUSH,
        ):
            if not enabled[channel]:
                continue
            try:
                payload_data = (
                    {"reply_markup": payload.telegram_reply_markup}
                    if channel == NotificationChannel.TELEGRAM
                    and payload.telegram_reply_markup
                    else None
                )
                log = dispatch_channel(
                    makerspace=makerspace,
                    channel=channel,
                    feature=feature,
                    event=event,
                    text_body=payload.text,
                    payload=payload_data,
                    sync=sync,
                )
            except Exception:
                _increment(failed, channel)
                logger.warning(
                    "lifecycle_channel_dispatch_failed",
                    extra={
                        "makerspace_id": getattr(makerspace, "pk", None),
                        "channel": channel,
                    },
                )
                continue
            if log.status == NotificationDeliveryStatus.SKIPPED:
                # Neither delivered nor failed -- the same reasoning as the email skip
                # above: the makerspace uninstalled this channel's module, and counting
                # a skip as a delivery makes `bool(delivered_counts)` claim a reminder
                # went out when nothing was sent.
                continue
            target = failed if log.status == NotificationDeliveryStatus.FAILED else delivered
            _increment(target, channel)
    except Exception:
        logger.warning(
            "lifecycle_notification_failed",
            extra={
                "makerspace_id": getattr(makerspace, "pk", None),
                "feature": feature,
                "event": event,
            },
        )
    return NotificationResult(False, delivered, failed)


def notify_lifecycle(makerspace, *, feature, event, build, sync=False):
    """Fan one lifecycle payload out according to the makerspace channel matrix."""
    if feature not in NotificationFeature.values or event not in FEATURE_EVENTS.get(feature, ()):
        logger.warning(
            "unknown_lifecycle_notification",
            extra={"feature": feature, "event": event},
        )
        return NotificationResult(False, {}, {})
    if sync:
        return _run_guarded(makerspace, feature, event, build, True)
    try:
        transaction.on_commit(
            lambda: _run_guarded(makerspace, feature, event, build, False),
            robust=True,
        )
    except Exception:
        logger.warning(
            "lifecycle_notification_schedule_failed",
            extra={
                "makerspace_id": getattr(makerspace, "pk", None),
                "feature": feature,
                "event": event,
            },
        )
        return NotificationResult(False, {}, {})
    return NotificationResult(True, {}, {})
