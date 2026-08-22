import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import DailyEmailCounter, EmailLog
from apps.integrations.smtp_validation import sanitize_email_error
from apps.makerspaces import domain_verification, limits

logger = logging.getLogger(__name__)

# Mail a makerspace may not switch off, matched on **stream AND event** -- an event name
# alone is not unique across streams, so matching on `event` would silently exempt an
# unrelated message that happened to share the name.
#
# The first two are account recovery. They are platform mail (`makerspace=None`) and so
# are already outside the tenant gate below; they are named here anyway because the gate
# must not become tenant-scoped by accident, and because losing `email_verification`
# leaves a new account unable to verify and therefore unable to join at all.
# `return_reminder` is an overdue-loan duty-of-care message tied to the accountability
# flow, not a notification preference.
EMAIL_MODULE_EXEMPT = frozenset({
    ("account", "password_reset"),
    ("account", "email_verification"),
    ("hardware", "return_reminder"),
    ("backup", "archive_custody_alarm"),
})


def email_module_blocks(makerspace, stream, event):
    """True when the `email` module is off for this makerspace and the mail is gateable.

    Platform mail has no makerspace and is never gated: there is no tenant whose toggle
    could apply, and gating it would take out forgot-password for everyone.
    """
    if makerspace is None:
        return False
    if (stream, event) in EMAIL_MODULE_EXEMPT:
        return False
    from apps.makerspaces.platform import module_enabled

    return not module_enabled(makerspace, "email")


def _create_email_log(**values):
    """Hold the shared fence across the mapped EmailLog insert."""
    from apps.encryption.write_fence import assert_mapped_write_allowed

    with transaction.atomic():
        makerspace = values.get("makerspace")
        assert_mapped_write_allowed(None if makerspace is None else makerspace.id)
        return EmailLog.objects.create(**values)


def dispatch_email(
    *,
    to_email,
    subject,
    text_body,
    html_body="",
    makerspace=None,
    stream="",
    event="",
    audience="",
    connection="makerspace",
    persist_body=True,
    sync=False,
):
    platform_minimized = settings.PII_ENCRYPTION_ENABLED and makerspace is None
    if platform_minimized:
        # Keyless platform mail is deliberately transient: it cannot be queued or retried.
        sync = True
        persist_body = False
        stream, event, audience = "platform", "platform_email", "system"
    if not persist_body and not sync:
        raise ValueError("persist_body=False requires sync=True")

    if email_module_blocks(makerspace, stream, event):
        # Recorded rather than dropped: the operator needs to see what their toggle
        # suppressed. The body is stored only when the caller allowed persistence --
        # a skipped row must not become the place a redacted body leaks into.
        return _create_email_log(
            makerspace=makerspace,
            to_email=to_email,
            subject=subject,
            text_body=text_body if persist_body else "",
            html_body=html_body if persist_body else "",
            stream=stream,
            event=event,
            audience=audience,
            connection_kind=connection,
            status=EmailLog.Status.SKIPPED,
            error="Email is disabled for this makerspace.",
        )

    if (
        not domain_verification.is_self_host()
        and makerspace is not None
        and connection == "makerspace"
    ):
        try:
            limit = limits.resource_limit(makerspace, "email")
            if limit is not None:
                with transaction.atomic():
                    from apps.encryption.write_fence import (
                        PiiWriteFenced,
                        assert_mapped_write_allowed,
                    )

                    assert_mapped_write_allowed(makerspace.id)
                    counter, _ = DailyEmailCounter.objects.get_or_create(
                        makerspace=makerspace,
                        day=timezone.now().date(),
                    )
                    counter = DailyEmailCounter.objects.select_for_update().get(
                        pk=counter.pk
                    )
                    if counter.count >= limit:
                        return EmailLog.objects.create(
                            makerspace=makerspace,
                            to_email=to_email,
                            subject=subject,
                            text_body=text_body if persist_body else "",
                            html_body=html_body if persist_body else "",
                            stream=stream,
                            event=event,
                            audience=audience,
                            connection_kind=connection,
                            status=EmailLog.Status.FAILED,
                            error="Daily email limit reached for this space.",
                        )
                    counter.count = counter.count + 1
                    counter.save(update_fields=["count"])
        except PiiWriteFenced:
            raise
        except Exception:
            logger.exception(
                "daily_email_limit_check_failed",
                extra={"makerspace_id": makerspace.pk},
            )

    # persist_body=False keeps the rendered body OUT of the stored row (e.g. password
    # reset emails embed a live recovery token in the body - persisting it would leave a
    # usable token in the DB + Django admin until expiry). We still deliver the real body:
    # it's set on the in-memory instance below and _deliver never re-saves the body fields.
    log = _create_email_log(
        makerspace=makerspace,
        to_email="" if platform_minimized else to_email,
        subject="Platform email" if platform_minimized else subject,
        text_body=text_body if persist_body else "",
        html_body=html_body if persist_body else "",
        stream=stream,
        event=event,
        audience=audience,
        connection_kind=connection,
    )
    if not persist_body:
        # In-memory only - _deliver's save(update_fields=...) excludes the body fields,
        # so the stored row stays redacted while delivery uses the real content.
        log.text_body = text_body
        log.html_body = html_body
    if platform_minimized:
        log.to_email = to_email
        log.subject = subject
    if sync:
        return _deliver(log)
    transaction.on_commit(lambda lid=log.id: _enqueue(lid))
    return log


def _enqueue(log_id):
    from apps.integrations.tasks import deliver_email_task

    try:
        deliver_email_task.delay(log_id)
    except Exception as exc:
        from apps.encryption.write_fence import assert_mapped_write_allowed

        with transaction.atomic():
            candidate = EmailLog.objects.only("makerspace_id").filter(pk=log_id).first()
            if candidate is not None:
                assert_mapped_write_allowed(candidate.makerspace_id)
                log = EmailLog.objects.select_for_update().get(pk=log_id)
                log.status = EmailLog.Status.FAILED
                log.error = sanitize_email_error(exc)
                log.save(update_fields=["status", "error", "updated_at"])
        logger.exception("email_enqueue_failed", extra={"email_log_id": log_id})


def _deliver(log):
    if log.status == EmailLog.Status.SENT:
        return log

    from apps.encryption.write_fence import assert_mapped_write_allowed

    with transaction.atomic():
        assert_mapped_write_allowed(log.makerspace_id)

    # Re-checked at delivery, not just at dispatch: a queued row can sit in Celery
    # across a module uninstall, and the retry path re-enters here too. Gating only
    # `dispatch_email` would let everything already in flight through.
    if email_module_blocks(log.makerspace, log.stream, log.event):
        log.status = EmailLog.Status.SKIPPED
        log.error = "Email is disabled for this makerspace."
        log.save(update_fields=["status", "error", "updated_at"])
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
