from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import Makerspace
from apps.notifications.emit import emit_notification
from apps.tenant_migration.gate_runtime import fanout_tenant_write


def run_return_reminders(*, now=None, limit=200) -> dict:
    now = now or timezone.now()
    limit = max(int(limit), 1)
    unavailable_makerspace_ids = set(
        Makerspace.objects.exclude(
            archived_at__isnull=True,
            lifecycle_state=Makerspace.LifecycleState.ACTIVE,
        ).values_list("pk", flat=True)
    )
    excluded_makerspace_ids = (
        unavailable_makerspace_ids | rbac.superadmin_hidden_makerspace_ids()
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
    counts = {"sent": 0, "skipped": 0}
    for hardware_request in queryset:
        with fanout_tenant_write(
            hardware_request.makerspace_id,
            operation="return_reminder",
            counts=counts,
        ) as should_process:
            if not should_process:
                continue
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
                counts["sent"] += 1
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
            counts["skipped"] += 1

    return counts
