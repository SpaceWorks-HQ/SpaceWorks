import logging

from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import EmailLog
from apps.integrations.smtp_validation import sanitize_email_error
from .dispatch_policy import email_module_blocks

logger = logging.getLogger(__name__)

def _deliver(log):
    if log.status in {EmailLog.Status.SENT, EmailLog.Status.SKIPPED}:
        return log

    if log.event == 'daily_digest':
        from apps.integrations.reminders_deferred import _allowed
        if not _allowed(log, log.makerspace):
            log.status, log.error = EmailLog.Status.SKIPPED, 'notification_disabled_before_release'
            log.save(update_fields=['status', 'error', 'updated_at'])
            return log

    from apps.encryption.write_fence import assert_mapped_write_allowed

    with transaction.atomic():
        assert_mapped_write_allowed(log.makerspace_id)

    # Re-checked at delivery, not just at dispatch: a queued row can sit in Celery
    # across a module uninstall, and the retry path re-enters here too. Gating only
    # `dispatch_email` would let everything already in flight through.
    from apps.integrations.email_preferences import blocked_reason, unsubscribe_headers
    reason = blocked_reason(log.makerspace, log.to_email, user_id=log.recipient_id,
                            feature=log.feature, stream=log.stream, event=log.event)
    if reason or email_module_blocks(log.makerspace, log.stream, log.event):
        log.status = EmailLog.Status.SKIPPED
        log.error = reason or "Email is disabled for this makerspace."
        log.save(update_fields=["status", "error", "updated_at"])
        return log

    from apps.integrations.timing_dispatch import defer_log
    if defer_log(log, kind='email'):
        return log

    try:
        from apps.integrations.email import (
            makerspace_mail_connection,
            platform_mail_connection,
        )

        if log.connection_kind == "makerspace" and log.makerspace_id:
            connection, from_email = makerspace_mail_connection(log.makerspace)
        else:
            connection, from_email = platform_mail_connection()
        msg = EmailMultiAlternatives(
            subject=log.subject,
            body=log.text_body,
            from_email=from_email,
            to=[log.to_email],
            connection=connection,
            headers=unsubscribe_headers(log),
        )
        if log.html_body:
            msg.attach_alternative(log.html_body, "text/html")
        msg.send()
    except Exception as exc:
        log.status = EmailLog.Status.FAILED
        log.error = sanitize_email_error(exc)
        logger.error(
            "email_delivery_failed",
            extra={"email_log_id": log.pk, "error_class": type(exc).__name__},
        )
        # Heads-up in the staff inbox on FIRST failure only (attempts is bumped in
        # `finally` below, so 0 here means the initial delivery attempt) — avoids a
        # row per retry. Fully fail-safe; never affects delivery.
        if log.attempts == 0 and log.makerspace_id:
            from apps.notifications.emit import emit_notification

            emit_notification(
                log.makerspace,
                level="warning",
                event="email.failed",
                title="Email delivery failed",
                body=f"Email log #{log.pk} delivery failed.",
            )
    else:
        log.status = EmailLog.Status.SENT
        log.error = ""
        log.sent_at = timezone.now()
    finally:
        log.attempts += 1
        log.save(
            update_fields=[
                "status",
                "error",
                "attempts",
                "sent_at",
                "updated_at",
            ]
        )
    return log
