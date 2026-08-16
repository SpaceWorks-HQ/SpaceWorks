from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import record
from apps.machines import access
from apps.machines.models import Machine
from apps.makerspaces.guards import require_module
from apps.makerspaces.servability import is_servable
from apps.maintenance.exceptions import (
    MaintenanceStatusConflict,
    RetiredMachineMaintenance,
)
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


def lock_machine(machine):
    return Machine.objects.select_for_update().select_related(
        "makerspace", "machine_type",
    ).get(pk=machine.pk)


def prepare_machine(machine, actor, *, manage):
    require_module(machine.makerspace, "maintenance")
    # Archived makerspaces are soft-deleted for everyone; reject after the row lock
    # reloads the makerspace so a per-machine operator can't complete an in-flight
    # mutation (and finalize an attachment) during the archive->purge window.
    if not is_servable(machine.makerspace):
        raise PermissionDenied()
    if not machine.is_active:
        raise RetiredMachineMaintenance("Machine is retired.")
    allowed = (
        access.can_manage_machine(actor, machine)
        if manage
        else access.can_operate_machine(actor, machine)
    )
    if not allowed:
        raise PermissionDenied()


def clean_text(value, field, *, allow_blank=False):
    if not isinstance(value, str):
        raise ValidationError({field: "Must be a string."})
    value = value.strip()
    if not value and not allow_blank:
        raise ValidationError({field: "This field may not be blank."})
    return value


def clean_interval(value):
    if isinstance(value, bool):
        raise ValidationError({"interval_days": "A positive integer is required."})
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValidationError({"interval_days": "A positive integer is required."})
    if value <= 0:
        raise ValidationError({"interval_days": "Must be greater than zero."})
    return value


def clean_date(value, field="next_due"):
    try:
        return MaintenanceSchedule._meta.get_field("next_due").clean(value, None)
    except (TypeError, ValueError):
        raise ValidationError({field: "Enter a valid date."})


def clean_performed_at(value):
    value = timezone.now() if value is None else value
    try:
        value = MaintenanceLog._meta.get_field("performed_at").clean(value, None)
    except (TypeError, ValueError):
        raise ValidationError({"performed_at": "Enter a valid date/time."})
    if timezone.is_naive(value):
        raise ValidationError({"performed_at": "Timezone information is required."})
    return value


def clean_cost(value):
    if value in (None, ""):
        return None
    try:
        value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"cost": "Enter a valid amount."})
    if not value.is_finite() or value < 0:
        raise ValidationError({"cost": "Must be zero or greater."})
    try:
        return MaintenanceLog._meta.get_field("cost").clean(value, None)
    except Exception:
        raise ValidationError({"cost": "Enter an amount with at most 10 whole digits and 2 decimals."})


def validate_log_values(*, summary, performed_at, cost, parts_note):
    return {
        "summary": clean_text(summary, "summary"),
        "performed_at": clean_performed_at(performed_at),
        "cost": clean_cost(cost),
        "parts_note": clean_text(parts_note or "", "parts_note", allow_blank=True),
    }


def ensure_idle_transition(machine, set_idle):
    if not set_idle:
        return
    if machine.status != Machine.Status.MAINTENANCE:
        raise MaintenanceStatusConflict(
            "Only a machine in maintenance can be set to idle."
        )


def apply_idle_transition(machine, actor):
    old_status = machine.status
    machine.status = Machine.Status.IDLE
    machine.save(update_fields=["status", "updated_at"])
    record(
        actor,
        "machine.status_changed",
        makerspace=machine.makerspace,
        target=machine,
        meta={"old": old_status, "new": Machine.Status.IDLE},
    )
