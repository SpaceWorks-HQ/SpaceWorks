from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest
from apps.notifications.emit import emit_notification
from apps.tenant_migration.gate_runtime import fanout_tenant_write


def run_return_reminders(*, now=None, limit=200) -> dict:
    counts = _run_legacy_return_reminders(now=now, limit=limit)
    from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
    from apps.operations.reminder_sweeper import run_reminder_sweep

    if rbac.scope_for_scheduled_work(MakerspaceLoanPolicy.objects.all()).exists():
        ladder = run_reminder_sweep(now=now, limit=max(int(limit), 1),
                                    source_keys=("loans.return", "loans.escalation"))
        counts["sent"] += ladder["dispatched"]
        counts["skipped"] += ladder["skipped"] + ladder["failed"]
    return counts


def _run_legacy_return_reminders(*, now=None, limit=200) -> dict:
    now = now or timezone.now()
    limit = max(int(limit), 1)
    # Keep frozen/not-restored tenants in the RBAC scan so the gate counts skips.
    queryset = _legacy_rows(now).select_related("makerspace", "requester").order_by("return_due_at", "id")[:limit]
    counts = {"sent": 0, "skipped": 0}
    for hardware_request in queryset:
        with fanout_tenant_write(
            hardware_request.makerspace_id,
            operation="return_reminder",
            counts=counts,
        ) as should_process:
            if not should_process:
                continue
            # A return, due-date edit or policy opt-in can commit after discovery.
            # Rebuild the subject under the boundary before claiming or sending.
            hardware_request = _legacy_rows(now).select_related("makerspace", "requester").filter(
                pk=hardware_request.pk, makerspace_id=hardware_request.makerspace_id,
            ).first()
            if hardware_request is None:
                counts["skipped"] += 1
                continue
            with transaction.atomic():
                claimed = _legacy_rows(now).filter(
                    pk=hardware_request.pk,
                ).update(return_reminder_sent_at=now)
            if not claimed:
                continue
            try:
                sent = notifications.notify_return_due(hardware_request)
            except Exception:
                rbac.scope_for_scheduled_work(HardwareRequest.objects.all(), makerspace_id=hardware_request.makerspace_id).filter(pk=hardware_request.pk).update(
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
            rbac.scope_for_scheduled_work(HardwareRequest.objects.all(), makerspace_id=hardware_request.makerspace_id).filter(pk=hardware_request.pk).update(
                return_reminder_sent_at=None
            )
            counts["skipped"] += 1

    return counts


def _legacy_rows(now):
    return rbac.scope_for_scheduled_work(HardwareRequest.objects.all()).filter(
        makerspace__loan_policy__isnull=True,
        status__in=[HardwareRequest.Status.ISSUED, HardwareRequest.Status.PARTIALLY_RETURNED],
        return_due_at__lte=now, return_reminder_sent_at__isnull=True,
    )
