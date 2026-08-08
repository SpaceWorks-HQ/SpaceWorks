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


def _channel_configured(makerspace, channel) -> bool:
    # The getters DECRYPT stored secrets. A missing/rotated API_CLIENT_ENC_KEY or corrupt
    # ciphertext makes decrypt raise here — before any log row exists. Swallow it: an
    # unreadable destination is treated as not-configured (terminal FAILED, no send, no
    # quota) so the fail-safe contract holds and a sync caller's fan-out never aborts.
    try:
        if channel == NonEmailNotificationChannel.TELEGRAM:
            # Mirror telegram.send_message's token resolution: a per-makerspace token OR
            # the global settings.TELEGRAM_BOT_TOKEN fallback, plus a group chat id. Without
            # the fallback here, a space relying on the global token would be wrongly treated
            # as not-configured and its lifecycle Telegram alerts would silently stop.
            from django.conf import settings

            token = makerspace.get_telegram_bot_token() or getattr(
                settings, "TELEGRAM_BOT_TOKEN", ""
            )
            return bool(token and makerspace.telegram_group_chat_id)
        if channel == NonEmailNotificationChannel.SLACK:
            return bool(makerspace.get_slack_webhook_url())
        if channel == NonEmailNotificationChannel.MATTERMOST:
            return bool(makerspace.get_mattermost_webhook_url())
        if channel == NonEmailNotificationChannel.DISCORD:
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
    *, makerspace, channel, feature, event, text_body, payload=None, sync=False
) -> NotificationDeliveryLog:
    if channel not in NonEmailNotificationChannel.values:
        raise ValueError(f"Unsupported notification channel: {channel}")

    if channel_module_blocks(makerspace, channel):
        return NotificationDeliveryLog.objects.create(
            makerspace=makerspace,
            channel=channel,
            feature=feature,
            event=event,
            text_body=text_body,
            payload=payload or {},
            status=NotificationDeliveryStatus.SKIPPED,
            error="notification_channel_module_disabled",
        )

    if not _channel_configured(makerspace, channel):
        return NotificationDeliveryLog.objects.create(
            makerspace=makerspace,
            channel=channel,
            feature=feature,
            event=event,
            text_body=text_body,
            payload=payload or {},
            status=NotificationDeliveryStatus.FAILED,
            error="notification_channel_not_configured",
        )

    if not limits.reserve_notification_quota(makerspace, channel):
        return NotificationDeliveryLog.objects.create(
            makerspace=makerspace,
            channel=channel,
            feature=feature,
            event=event,
            text_body=text_body,
            payload=payload or {},
            status=NotificationDeliveryStatus.FAILED,
            error=f"Daily {channel} notification limit reached for this space.",
        )

    log = NotificationDeliveryLog.objects.create(
        makerspace=makerspace,
        channel=channel,
        feature=feature,
        event=event,
        text_body=text_body,
        payload=payload or {},
        status=NotificationDeliveryStatus.PENDING,
    )
    if sync:
        return _deliver_notification(log)
    transaction.on_commit(
        lambda lid=log.id: _enqueue_notification(lid), robust=True
    )
    return log


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


def _deliver_notification(log) -> NotificationDeliveryLog:
    if log.status == NotificationDeliveryStatus.SENT:
        return log

    # Re-checked here, not only at dispatch: a PENDING row can sit in the Celery queue
    # across a module uninstall, and a retry re-enters through this function. Without
    # this the toggle would be honoured for new alerts but not for queued ones.
    if channel_module_blocks(log.makerspace, log.channel):
        log.status = NotificationDeliveryStatus.SKIPPED
        log.error = "notification_channel_module_disabled"
        log.save(update_fields=["status", "error", "updated_at"])
        return log

    try:
        if log.channel == NonEmailNotificationChannel.NATIVE_PUSH:
            from apps.integrations.push import deliver_native_push

            ok = deliver_native_push(log)
        elif log.channel == NonEmailNotificationChannel.TELEGRAM:
            from apps.integrations.telegram import send_message

            ok = send_message(
                log.makerspace,
                log.text_body,
                reply_markup=(log.payload or {}).get("reply_markup"),
            )
        else:
            from apps.integrations.webhooks import send_webhook

            ok = send_webhook(
                log.makerspace,
                channel=log.channel,
                text=log.text_body,
            )
    except Exception as exc:
        log.status = NotificationDeliveryStatus.FAILED
        log.error = sanitize_notification_error(exc)
        _redact_exception_for_logging(exc)
        logger.exception(
            "notification_delivery_failed",
            extra={"notification_log_id": log.pk, "channel": log.channel},
        )
    else:
        if ok is True:
            log.status = NotificationDeliveryStatus.SENT
            log.error = ""
            log.sent_at = timezone.now()
        else:
            log.status = NotificationDeliveryStatus.FAILED
            log.error = "notification_channel_not_configured"
    finally:
        log.attempts += 1
        log.save(
            update_fields=["status", "error", "attempts", "sent_at", "updated_at"]
        )
    return log
