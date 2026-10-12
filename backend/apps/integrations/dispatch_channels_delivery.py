"""Provider delivery behind the stable non-email dispatch barrel."""

import logging
from django.utils import timezone
from apps.integrations.models import NotificationDeliveryStatus, NotificationDeliveryLog, NonEmailNotificationChannel
from .dispatch_channels import channel_module_blocks, sanitize_notification_error, _redact_exception_for_logging

logger = logging.getLogger(__name__)

def _deliver_notification(log) -> NotificationDeliveryLog:
    if log.status in {NotificationDeliveryStatus.SENT, NotificationDeliveryStatus.SKIPPED}:
        return log

    # Re-checked here, not only at dispatch: a PENDING row can sit in the Celery queue
    # across a module uninstall, and a retry re-enters through this function. Without
    # this the toggle would be honoured for new alerts but not for queued ones.
    if channel_module_blocks(log.makerspace, log.channel):
        log.status = NotificationDeliveryStatus.SKIPPED
        log.error = "notification_channel_module_disabled"
        log.save(update_fields=["status", "error", "updated_at"])
        return log

    if log.destination_id is None and log.destination_label:
        # The room was deleted while this row waited in the queue. Falling through would
        # send via the makerspace-wide credential, posting a room-scoped alert into the
        # general channel — so this is terminal instead.
        log.status = NotificationDeliveryStatus.FAILED
        log.error = "notification_destination_deleted"
        log.attempts += 1
        log.save(update_fields=["status", "error", "attempts", "updated_at"])
        return log

    from apps.integrations.timing_dispatch import defer_log
    if defer_log(log, kind='channel'):
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
                destination=log.destination,
            )
        elif log.channel == NonEmailNotificationChannel.WEBHOOK:
            from apps.integrations.webhooks import send_signed_webhook

            ok = send_signed_webhook(log)
        else:
            from apps.integrations.webhooks import send_webhook

            ok = send_webhook(
                log.makerspace,
                channel=log.channel,
                text=log.text_body,
                destination=log.destination,
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
