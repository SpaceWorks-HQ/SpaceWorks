import logging
import re

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import (
    NonEmailNotificationChannel,
    NotificationDeliveryLog,
    NotificationDeliveryStatus,
)
from apps.makerspaces import limits

logger = logging.getLogger(__name__)


def sanitize_notification_error(exc) -> str:
    class_name = re.sub(r"[^A-Za-z0-9_]", "", exc.__class__.__name__)
    return f"notification_delivery_failed:{class_name or 'UnknownError'}"[:2000]


def _redact_exception_for_logging(exc) -> None:
    """Keep provider destinations and bodies out of exception tracebacks."""
    try:
        exc.args = (sanitize_notification_error(exc),)
        exc.__cause__ = None
        exc.__context__ = None
    except Exception:
        pass


def _channel_configured(makerspace, channel, destination=None) -> bool:
    # The getters DECRYPT stored secrets. A missing/rotated API_CLIENT_ENC_KEY or corrupt
    # ciphertext makes decrypt raise here — before any log row exists. Swallow it: an
    # unreadable destination is treated as not-configured (terminal FAILED, no send, no
    # quota) so the fail-safe contract holds and a sync caller's fan-out never aborts.
    try:
        if channel == NonEmailNotificationChannel.TELEGRAM:
            # A destination supplies the chat id only; the bot is always the makerspace's
            # (D16). A destination that resolves to no token at all is not-configured —
            # a terminal FAILED row, never a silent skip.
            from apps.integrations.telegram import resolve_bot_token, resolve_chat_id

            return bool(
                resolve_bot_token(makerspace)
                and resolve_chat_id(makerspace, destination)
            )
        if channel == NonEmailNotificationChannel.WEBHOOK:
            # Destination-only: there is no makerspace-wide signed endpoint, and a
            # destination without a signing secret is not-configured, never unsigned.
            return destination is not None and bool(
                destination.get_webhook_url() and destination.get_signing_secret()
            )
        if channel in (
            NonEmailNotificationChannel.SLACK,
            NonEmailNotificationChannel.MATTERMOST,
            NonEmailNotificationChannel.DISCORD,
        ):
            if destination is not None:
                return bool(destination.get_webhook_url())
            if channel == NonEmailNotificationChannel.SLACK:
                return bool(makerspace.get_slack_webhook_url())
            if channel == NonEmailNotificationChannel.MATTERMOST:
                return bool(makerspace.get_mattermost_webhook_url())
            return bool(makerspace.get_discord_webhook_url())
        if channel == NonEmailNotificationChannel.NATIVE_PUSH:
            from apps.integrations.push import push_configured

            return push_configured()
        return False
    except Exception:
        logger.warning(
            "notification_channel_config_unreadable",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "channel": channel},
        )
        return False


def channel_module_blocks(makerspace, channel) -> bool:
    """True when this channel's module is uninstalled for the makerspace.

    An additive AND in front of the credential check that already existed: enabling the
    key cannot make an unconfigured channel send, and disabling it stops sending while
    the stored webhook survives, so re-enabling needs no credential re-entry.

    Fails OPEN on an unexpected error, matching every other guard in this file: a broken
    capability lookup must not silently mute a makerspace's alerts.
    """
    from apps.integrations.models import CHANNEL_MODULE_KEYS

    key = CHANNEL_MODULE_KEYS.get(channel)
    if key is None or makerspace is None:
        return False
    try:
        from apps.makerspaces.platform import module_enabled

        return not module_enabled(makerspace, key)
    except Exception:
        logger.warning(
            "notification_channel_module_check_failed",
            extra={"makerspace_id": getattr(makerspace, "pk", None), "channel": channel},
        )
        return False


def dispatch_channel(
    *,
    makerspace,
    channel,
    feature,
    event,
    text_body,
    payload=None,
    sync=False,
    scope=None,
) -> list[NotificationDeliveryLog]:
    """Fan one alert out to every matching destination on a channel.

    Returns **one log row per destination** (D13), so a failure is attributable to a
    specific room rather than to "Slack". Quota is charged per row, because N rooms is N
    real sends and that is what costs.
    """
    if channel not in NonEmailNotificationChannel.values:
        raise ValueError(f"Unsupported notification channel: {channel}")

    # Push resolves its recipients at delivery time, so the alert's subject has to travel
    # on the row or a narrowed recipient rule would match nothing by then.
    stored_payload = dict(payload or {})
    if scope is not None and hasattr(scope, "as_dict"):
        stored_payload["scope"] = scope.as_dict()

    def record(status, error="", destination=None):
        return NotificationDeliveryLog.objects.create(
            makerspace=makerspace,
            channel=channel,
            destination=destination,
            destination_label=getattr(destination, "label", "") or "",
            feature=feature,
            event=event,
            text_body=text_body,
            payload=stored_payload,
            status=status,
            error=error,
        )

    if channel_module_blocks(makerspace, channel):
        # Checked before destinations are resolved: a tombstoned or uninstalled channel
        # module short-circuits before any room is considered.
        return [
            record(
                NotificationDeliveryStatus.SKIPPED,
                "notification_channel_module_disabled",
            )
        ]

    if channel == NonEmailNotificationChannel.NATIVE_PUSH:
        # Push has no room to address: it is delivered per device to a named user, so it
        # keeps the single-log shape with a null destination.
        targets = [None]
    else:
        from apps.integrations.destinations import resolve_destinations

        targets = resolve_destinations(makerspace, channel, scope)
        if not targets:
            # Rooms exist but none of them asked for this subject. Recorded rather than
            # dropped so an operator can see the alert had nowhere in-scope to go, and
            # SKIPPED rather than FAILED because nothing is broken.
            return [
                record(
                    NotificationDeliveryStatus.SKIPPED,
                    "notification_no_matching_destination",
                )
            ]

    logs = []
    for destination in targets:
        if not _channel_configured(makerspace, channel, destination):
            logs.append(
                record(
                    NotificationDeliveryStatus.FAILED,
                    "notification_channel_not_configured",
                    destination=destination,
                )
            )
            continue

        if not limits.reserve_notification_quota(makerspace, channel):
            logs.append(
                record(
                    NotificationDeliveryStatus.FAILED,
                    f"Daily {channel} notification limit reached for this space.",
                    destination=destination,
                )
            )
            continue

        log = record(NotificationDeliveryStatus.PENDING, destination=destination)
        from apps.integrations.timing_dispatch import defer_log
        if defer_log(log, kind='channel'):
            logs.append(log)
            continue
        if sync:
            logs.append(_deliver_notification(log))
        else:
            transaction.on_commit(
                lambda lid=log.id: _enqueue_notification(lid), robust=True
            )
            logs.append(log)
    return logs


def _enqueue_notification(log_id):
    from apps.integrations.tasks import deliver_notification_task

    try:
        deliver_notification_task.delay(log_id)
    except Exception as exc:
        NotificationDeliveryLog.objects.filter(pk=log_id).update(
            status=NotificationDeliveryStatus.FAILED,
            error=sanitize_notification_error(exc),
        )
        _redact_exception_for_logging(exc)
        logger.exception(
            "notification_enqueue_failed",
            extra={"notification_log_id": log_id},
        )


from .dispatch_channels_delivery import _deliver_notification  # noqa: E402,F401
