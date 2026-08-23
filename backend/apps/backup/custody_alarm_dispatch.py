import logging
import uuid
from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from apps.integrations.dispatch import dispatch_email
from apps.integrations.models import EmailLog
from apps.integrations.smtp_validation import sanitize_email_error
from apps.makerspaces.platform import module_enabled
from apps.notifications.models import Notification

from .custody_alarm_recipients import alarm_message
from .models import ArchiveCustodyAlarmDelivery, MakerspaceArchiveCustodyState


logger = logging.getLogger(__name__)
CLAIM_LEASE = timedelta(minutes=10)
SEND_TIMEOUT = 30
MAX_ATTEMPTS = 5
MAX_ROWS_PER_SWEEP = 200


def deliver_claimable_rows(
    *,
    makerspace_id=None,
    limit=MAX_ROWS_PER_SWEEP,
    delivery_model=ArchiveCustodyAlarmDelivery,
    state_model=MakerspaceArchiveCustodyState,
    event="archive_custody_alarm",
    custody_label="Archive",
):
    delivered = 0
    for _index in range(limit):
        claim = _claim_next(
            makerspace_id=makerspace_id,
            delivery_model=delivery_model,
        )
        if claim is None:
            break
        _dispatch_claim(
            *claim,
            delivery_model=delivery_model,
            state_model=state_model,
            event=event,
            custody_label=custody_label,
        )
        delivered += 1
    return delivered


def _claim_next(*, makerspace_id, delivery_model=ArchiveCustodyAlarmDelivery):
    while True:
        now = timezone.now()
        expired_at = now - CLAIM_LEASE
        ready = (
            Q(status=delivery_model.Status.PENDING)
            | Q(
                status=delivery_model.Status.FAILED,
                next_attempt_at__lte=now,
            )
            | Q(
                status=delivery_model.Status.FAILED,
                next_attempt_at__isnull=True,
            )
            | Q(
                status=delivery_model.Status.SENDING,
                claimed_at__lt=expired_at,
            )
        )
        candidates = delivery_model.objects.filter(
            ready,
            attempts__lt=MAX_ATTEMPTS,
        )
        if makerspace_id is not None:
            candidates = candidates.filter(makerspace_id=makerspace_id)
        candidate_id = candidates.order_by("created_at", "pk").values_list(
            "pk", flat=True
        ).first()
        if candidate_id is None:
            return None

        token = uuid.uuid4()
        claimed = delivery_model.objects.filter(
            pk=candidate_id,
            attempts__lt=MAX_ATTEMPTS,
        ).filter(ready).update(
            status=delivery_model.Status.SENDING,
            claimed_at=now,
            claim_token=token,
        )
        if claimed:
            return candidate_id, token


def _dispatch_claim(
    delivery_id,
    claim_token,
    *,
    delivery_model=ArchiveCustodyAlarmDelivery,
    state_model=MakerspaceArchiveCustodyState,
    event="archive_custody_alarm",
    custody_label="Archive",
):
    delivery = (
        delivery_model.objects.select_related(
            "makerspace", "recipient_user"
        )
        .filter(pk=delivery_id, claim_token=claim_token)
        .first()
    )
    if delivery is None:
        return
    email_log = None
    notification = None
    try:
        if delivery.channel == delivery_model.Channel.TENANT_INAPP:
            notification = _dispatch_inapp(
                delivery,
                state_model=state_model,
                event=event,
                custody_label=custody_label,
            )
        else:
            email_log = _dispatch_email(
                delivery,
                delivery_model=delivery_model,
                state_model=state_model,
                event=event,
                custody_label=custody_label,
            )
            if email_log.status != EmailLog.Status.SENT:
                raise RuntimeError(email_log.error or "email_dispatch_failed")
    except Exception as exc:
        _record_failure(
            delivery,
            claim_token,
            exc,
            email_log=email_log,
            delivery_model=delivery_model,
        )
        return

    updated = delivery_model.objects.filter(
        pk=delivery.pk,
        claim_token=claim_token,
    ).update(
        status=delivery_model.Status.SENT,
        claimed_at=None,
        claim_token=None,
        next_attempt_at=None,
        email_log=email_log,
        notification=notification,
        last_error="",
        updated_at=timezone.now(),
    )
    if not updated:
        logger.warning(
            "archive_custody_alarm_stale_completion",
            extra={"delivery_id": delivery.pk},
        )


def _dispatch_email(
    delivery,
    *,
    delivery_model=ArchiveCustodyAlarmDelivery,
    state_model=MakerspaceArchiveCustodyState,
    event="archive_custody_alarm",
    custody_label="Archive",
):
    user = delivery.recipient_user
    if user is None or not user.email.strip():
        raise RuntimeError("custody_alarm_recipient_unavailable")
    custody_state = state_model.objects.get(
        makerspace_id=delivery.makerspace_id
    )
    recipient_count = delivery.makerspace.archive_recipients.filter(
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).count()
    operator = delivery.channel == delivery_model.Channel.OPERATOR_EMAIL
    subject, body = alarm_message(
        delivery.makerspace,
        custody_state,
        recipient_count,
        operator=operator,
        custody_label=custody_label,
    )
    return dispatch_email(
        to_email=user.email,
        subject=subject,
        text_body=body,
        makerspace=None if operator else delivery.makerspace,
        stream="backup",
        event=event,
        audience="operator" if operator else "staff",
        connection="platform" if operator else "makerspace",
        sync=True,
    )


def _dispatch_inapp(
    delivery,
    *,
    state_model=MakerspaceArchiveCustodyState,
    event="archive_custody_alarm",
    custody_label="Archive",
):
    if not module_enabled(delivery.makerspace, "notifications"):
        raise RuntimeError("notifications_module_unavailable")
    from apps.tenant_migration.gate_runtime import boundary_tenant_write

    custody_state = state_model.objects.get(
        makerspace_id=delivery.makerspace_id
    )
    recipient_count = delivery.makerspace.archive_recipients.filter(
        verified_at__isnull=False,
        revoked_at__isnull=True,
        compromised_at__isnull=True,
    ).count()
    title, body = alarm_message(
        delivery.makerspace,
        custody_state,
        recipient_count,
        operator=False,
        custody_label=custody_label,
    )
    with boundary_tenant_write(delivery.makerspace_id):
        return Notification.objects.create(
            makerspace=delivery.makerspace,
            level=Notification.Level.CRITICAL,
            event=event,
            title=title,
            body=body,
        )


def _record_failure(
    delivery,
    claim_token,
    exc,
    *,
    email_log,
    delivery_model=ArchiveCustodyAlarmDelivery,
):
    attempts = delivery.attempts + 1
    exhausted = attempts >= MAX_ATTEMPTS
    error = sanitize_email_error(exc)[:200] or type(exc).__name__
    updated = delivery_model.objects.filter(
        pk=delivery.pk,
        claim_token=claim_token,
    ).update(
        status=(
            delivery_model.Status.EXHAUSTED
            if exhausted
            else delivery_model.Status.FAILED
        ),
        attempts=F("attempts") + 1,
        claimed_at=None,
        claim_token=None,
        next_attempt_at=(
            None
            if exhausted
            else timezone.now() + timedelta(minutes=2 ** attempts)
        ),
        email_log=email_log,
        last_error=error,
        updated_at=timezone.now(),
    )
    if updated:
        logger.error(
            "archive_custody_alarm_dispatch_failed",
            extra={
                "delivery_id": delivery.pk,
                "makerspace_id": delivery.makerspace_id,
                "attempts": attempts,
                "exhausted": exhausted,
                "error_class": type(exc).__name__,
            },
        )
