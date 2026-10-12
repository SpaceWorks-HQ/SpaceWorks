"""Bounded F1 cleanup; unread inbox and in-flight deliveries are never selected."""

import logging
from datetime import timedelta

from django.db.models import Q
from django.db import transaction

from apps.accounts import rbac
from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.makerspaces.models import Makerspace
from apps.notifications.models_inbox import NotificationInboxRow
from apps.tenant_migration.gate_runtime import fanout_tenant_write

logger = logging.getLogger(__name__)
READ_INBOX_DAYS = 90
SENT_DELIVERY_DAYS = 90
FAILED_DELIVERY_DAYS = 365


def sweep_tenant_retention(space, *, now, limit):
    cutoff = now - timedelta(days=READ_INBOX_DAYS)
    inbox = rbac.scope_for_scheduled_work(
        NotificationInboxRow.objects.all(), makerspace_id=space.pk,
    ).filter(read_at__lt=cutoff)
    count = _delete_batch(inbox, limit)
    for model in (EmailLog, NotificationDeliveryLog):
        eligible = _terminal_rows(rbac.scope_for_scheduled_work(
            model.objects.all(), makerspace_id=space.pk,
        ), now)
        count += _delete_batch(eligible, limit)
    return count


def _terminal_rows(queryset, now):
    return queryset.filter(
        Q(status="sent", sent_at__lt=now - timedelta(days=SENT_DELIVERY_DAYS))
        | Q(status="failed", updated_at__lt=now - timedelta(days=FAILED_DELIVERY_DAYS))
        | Q(status="skipped", updated_at__lt=now - timedelta(days=SENT_DELIVERY_DAYS))
    )


def _delete_batch(queryset, limit):
    # Keep eligibility stable against a concurrent retry claim until deletion commits.
    with transaction.atomic():
        ids = list(queryset.select_for_update(skip_locked=True).order_by("pk").values_list("pk", flat=True)[:limit])
        queryset.filter(pk__in=ids).delete()
        return len(ids)


def run_notification_retention(*, now, limit):
    if type(limit) is not int or limit < 1:
        raise ValueError("Notification retention batch size must be a positive integer.")
    counts = {"deleted": 0, "skipped": 0, "failed": 0}
    # Platform recovery mail has no tenant gate, but shares the same telemetry windows.
    try:
        counts["deleted"] += _delete_batch(_terminal_rows(EmailLog.objects.filter(makerspace=None), now), limit)
    except Exception as exc:
        counts["failed"] += 1
        logger.error("platform_email_retention_failed", extra={"failure_type": type(exc).__name__})
    for space in rbac.scope_for_scheduled_work(Makerspace.objects.all(), field="pk").order_by("pk").iterator():
        try:
            with fanout_tenant_write(space.pk, operation="notification_retention", counts=counts) as permitted:
                if not permitted:
                    continue
                counts["deleted"] += sweep_tenant_retention(space, now=now, limit=limit)
        except Exception as exc:
            counts["failed"] += 1
            logger.error("notification_retention_failed", extra={
                "makerspace_id": space.pk, "failure_type": type(exc).__name__,
            })
    return counts
