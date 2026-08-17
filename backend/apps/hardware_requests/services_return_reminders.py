from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest
from apps.notifications.emit import emit_notification
from apps.tenant_migration.gate_runtime import tenant_write


def run_return_reminders(*, now=None, limit=200) -> dict:
    now = now or timezone.now()
    limit = max(int(limit), 1)
    excluded_makerspace_ids = (
        rbac.archived_makerspace_ids() | rbac.superadmin_hidden_makerspace_ids()
    )
    queryset = (
        HardwareRequest.objects.select_related("makerspace", "requester")
        .filter(
            status__in=[
                HardwareRequest.Status.ISSUED,
                HardwareRequest.Status.PARTIALLY_RETURNED,
            ],
            return_due_at__lte=now,
            return_reminder_sent_at__isnull=True,
        )
        .exclude(makerspace_id__in=excluded_makerspace_ids)
        .order_by("return_due_at", "id")[:limit]
    )
    sent_count = 0
    skipped_count = 0
    for hardware_request in queryset:
        with tenant_write(hardware_request.makerspace_id):
            with transaction.atomic():
                claimed = HardwareRequest.objects.filter(
                    pk=hardware_request.pk,
                    return_reminder_sent_at__isnull=True,
                ).update(return_reminder_sent_at=now)
            if not claimed:
                continue
            try:
                sent = notifications.notify_return_due(hardware_request)
            except Exception:
                HardwareRequest.objects.filter(pk=hardware_request.pk).update(
                    return_reminder_sent_at=None
                )
                raise
            if sent:
                sent_count += 1
                emit_notification(
                    hardware_request.makerspace,
                    level="warning",
                    event="loan.overdue",
                    title="Overdue loan reminder sent",
                    body=f"Request #{hardware_request.pk} is overdue; a reminder was sent.",
                )
                continue
            HardwareRequest.objects.filter(pk=hardware_request.pk).update(
                return_reminder_sent_at=None
            )
            skipped_count += 1

    return {"sent": sent_count, "skipped": skipped_count}
