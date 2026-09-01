"""Fail-safe lifecycle notification fan-out."""

import logging
from dataclasses import dataclass, field

from django.db import transaction

from apps.integrations import notification_rules
from apps.integrations.chat_templates import render_chat_text
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
    # What this alert is about, for destination scoping. It rides on the payload rather
    # than being a `notify_lifecycle` parameter because only `build()` has resolved the
    # domain object — the caller often has just a primary key. `None` means the alert
    # names no subject, and a room scoped to one machine will not receive it.
    scope: object | None = None
    # Staff-audience template variables for an editable chat body. `None` means this
    # adapter has no editable chat wording yet and `text` is sent verbatim — which is
    # also what happens when a space has authored no ChatTemplate row.
    context: dict | None = None


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
        # Rendered once for all chat channels: one stored body per event, not one per
        # channel. Falls back to `payload.text` whenever no row is authored.
        chat_text = render_chat_text(
            makerspace, feature, event, payload.text, payload.context
        )
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
                logs = dispatch_channel(
                    makerspace=makerspace,
                    channel=channel,
                    feature=feature,
                    event=event,
                    text_body=(
                        # Native push is not a room: it is the member's own device, and
                        # it must not inherit a chat body written for a staff channel.
                        payload.text
                        if channel == NotificationChannel.NATIVE_PUSH
                        else chat_text
                    ),
                    sync=sync,
                    scope=payload.scope,
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
            for log in logs:
                if log.status == NotificationDeliveryStatus.SKIPPED:
                    # Neither delivered nor failed -- the same reasoning as the email skip
                    # above: the makerspace uninstalled this channel's module, and counting
                    # a skip as a delivery makes `bool(delivered_counts)` claim a reminder
                    # went out when nothing was sent.
                    continue
                target = (
                    failed
                    if log.status == NotificationDeliveryStatus.FAILED
                    else delivered
                )
                # Counted per room, so three rooms is three deliveries: the counts back
                # `bool(delivered_counts)`, and a partial fan-out must show both sides.
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
