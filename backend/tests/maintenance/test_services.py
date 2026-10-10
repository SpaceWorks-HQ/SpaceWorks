from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineOperator
from apps.maintenance import services
from apps.maintenance.exceptions import (
    InactiveMaintenanceSchedule,
    MaintenanceStatusConflict,
    RetiredMachineMaintenance,
)
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule
from tests.maintenance.helpers import make_machine_setup


pytestmark = pytest.mark.django_db


def test_access_reuses_machine_operate_and_manage_tiers():
    _, manager, machine, operator = make_machine_setup(
        "maintenance-service-access",
        operator_level=MachineOperator.AccessLevel.OPERATE,
    )
    log = services.log_maintenance(
        machine, actor=operator, summary="Lubricated rails",
    )
    assert log.performed_by == operator
    with pytest.raises(PermissionDenied):
        services.create_schedule(
            machine, actor=operator, description="Monthly service",
            interval_days=30, next_due=timezone.localdate(),
        )
    schedule = services.create_schedule(
        machine, actor=manager, description="Monthly service",
        interval_days=30, next_due=timezone.localdate(),
    )
    assert schedule.created_by == manager


def test_logging_and_completion_are_audited_and_atomic(monkeypatch):
    _, manager, machine, _ = make_machine_setup("maintenance-service-complete")
    due = timezone.localdate() - timedelta(days=45)
    schedule = services.create_schedule(
        machine, actor=manager, description="Calibrate",
        interval_days=30, next_due=due,
    )
    log = services.complete_due(
        schedule, actor=manager, summary="Calibration complete",
        cost=Decimal("5.00"), parts_note="New belt",
    )
    schedule.refresh_from_db()
    next_due = timezone.localdate(log.performed_at) + timedelta(days=30)
    assert schedule.next_due == next_due
    assert log.cost == Decimal("5.00")
    assert set(
        AuditLog.objects.filter(
            target_id__in=[str(log.pk), str(schedule.pk)],
        ).values_list("action", flat=True)
    ) >= {"maintenance.logged", "maintenance.schedule_completed"}
    for entry in AuditLog.objects.filter(action__startswith="maintenance."):
        assert "Calibration complete" not in str(entry.meta)
        assert "New belt" not in str(entry.meta)

    def fail(*args, **kwargs):
        raise RuntimeError("audit down")

    monkeypatch.setattr("apps.maintenance.services_workflows.record", fail)
    before = MaintenanceLog.objects.count()
    with pytest.raises(RuntimeError):
        services.complete_due(
            schedule, actor=manager, summary="Should roll back",
        )
    schedule.refresh_from_db()
    assert schedule.next_due == next_due
    assert MaintenanceLog.objects.count() == before


def test_status_conflict_retired_and_inactive_fail_without_partial_writes():
    _, manager, machine, _ = make_machine_setup("maintenance-service-conflicts")
    with pytest.raises(MaintenanceStatusConflict):
        services.log_maintenance(
            machine, actor=manager, summary="No write", set_idle=True,
        )
    assert MaintenanceLog.objects.count() == 0
    machine.status = Machine.Status.MAINTENANCE
    machine.save(update_fields=["status"])
    services.log_maintenance(
        machine, actor=manager, summary="Done", set_idle=True,
    )
    machine.refresh_from_db()
    assert machine.status == Machine.Status.IDLE

    schedule = services.create_schedule(
        machine, actor=manager, description="One way", interval_days=7,
        next_due=timezone.localdate(),
    )
    services.deactivate_schedule(schedule, actor=manager)
    audit_count = AuditLog.objects.filter(
        action="maintenance.schedule_deactivated",
    ).count()
    services.deactivate_schedule(schedule, actor=manager)
    assert AuditLog.objects.filter(
        action="maintenance.schedule_deactivated",
    ).count() == audit_count
    with pytest.raises(InactiveMaintenanceSchedule):
        services.complete_due(schedule, actor=manager, summary="No")

    machine.is_active = False
    machine.save(update_fields=["is_active"])
    with pytest.raises(RetiredMachineMaintenance):
        services.log_maintenance(machine, actor=manager, summary="No")


def test_archived_makerspace_rejects_maintenance_mutation():
    makerspace, manager, machine, _ = make_machine_setup("maintenance-archived")
    makerspace.archived_at = timezone.now()
    makerspace.save(update_fields=["archived_at"])
    with pytest.raises(PermissionDenied):
        services.log_maintenance(machine, actor=manager, summary="After archive")
