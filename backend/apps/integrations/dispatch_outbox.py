import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.integrations.models import DailyEmailCounter, EmailLog
from apps.integrations.smtp_validation import sanitize_email_error
from apps.makerspaces import domain_verification, limits
from .dispatch_policy import email_module_blocks

logger = logging.getLogger(__name__)

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
    recipient_id=None,
    feature="",
):
    from apps.integrations.dispatch import _deliver

    platform_minimized = settings.PII_ENCRYPTION_ENABLED and makerspace is None
    if platform_minimized:
        # Keyless platform mail is deliberately transient: it cannot be queued or retried.
        sync = True
        persist_body = False
        stream, event, audience = "platform", "platform_email", "system"
    if not persist_body and not sync:
        raise ValueError("persist_body=False requires sync=True")

    from apps.integrations.email_preferences import blocked_reason
    reason = blocked_reason(makerspace, to_email, user_id=recipient_id,
                            feature=feature, stream=stream, event=event)
    if reason or email_module_blocks(makerspace, stream, event):
        # Recorded rather than dropped: the operator needs to see what their toggle
        # suppressed. The body is stored only when the caller allowed persistence --
        # a skipped row must not become the place a redacted body leaks into.
        return _create_email_log(
            makerspace=makerspace,
            to_email="" if platform_minimized else to_email,
            subject="Platform email" if platform_minimized else subject,
            text_body=text_body if persist_body else "",
            html_body=html_body if persist_body else "",
            stream=stream,
            event=event,
            audience=audience,
            connection_kind=connection,
            recipient_id=recipient_id,
            feature=feature,
            status=EmailLog.Status.SKIPPED,
            error=reason or "Email is disabled for this makerspace.",
        )

    if (
        not domain_verification.is_self_host()
        and makerspace is not None
        and connection == "makerspace"
    ):
        # Imported BEFORE the try: `except PiiWriteFenced` below names it, and a failure
        # raised ahead of an in-try import (the quota lookup itself) would otherwise turn
        # the intended logged fail-open into UnboundLocalError out of the mail path.
        from apps.encryption.write_fence import (
            PiiWriteFenced,
            assert_mapped_write_allowed,
        )

        try:
            limit = limits.resource_limit(makerspace, "email")
            if limit is not None:
                with transaction.atomic():
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
                            recipient_id=recipient_id,
                            feature=feature,
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
        recipient_id=recipient_id,
        feature=feature,
    )
    if not persist_body:
        # In-memory only - _deliver's save(update_fields=...) excludes the body fields,
        # so the stored row stays redacted while delivery uses the real content.
        log.text_body = text_body
        log.html_body = html_body
        log._timing_ineligible = True
    if platform_minimized:
        log.to_email = to_email
        log.subject = subject
    if persist_body and makerspace is not None:
        from apps.integrations.timing_dispatch import defer_log
        if defer_log(log, kind='email'):
            return log
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
        logger.error(
            "email_enqueue_failed",
            extra={"email_log_id": log_id, "error_class": type(exc).__name__},
        )
