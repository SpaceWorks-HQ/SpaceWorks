from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import record
from apps.accounts import rbac
from apps.maintenance.exceptions import InactiveMaintenanceSchedule
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule
from apps.maintenance.recurrence import clean_anchor, next_due_after_completion
from apps.maintenance.notifications import notify_maintenance_lifecycle
from apps.maintenance.services_shared import (
    apply_idle_transition,
    clean_date,
    clean_interval,
    clean_text,
    ensure_idle_transition,
    lock_machine,
    prepare_machine,
    validate_log_values,
)


def _append_log(machine, actor, values):
    log = MaintenanceLog.objects.create(
        machine=machine,
        performed_by=actor,
        **values,
    )
    metadata = {"machine_id": machine.pk}
    if values["cost"] is not None:
        metadata["cost"] = str(values["cost"])
    record(
        actor,
        "maintenance.logged",
        makerspace=machine.makerspace,
        target=log,
        meta=metadata,
    )
    return log


@transaction.atomic
def log_maintenance(
    machine, *, actor, summary, performed_at=None, cost=None,
    parts_note="", set_idle=False,
):
    machine = lock_machine(machine, actor)
    prepare_machine(machine, actor, manage=False)
    ensure_idle_transition(machine, set_idle)
    values = validate_log_values(
        summary=summary, performed_at=performed_at, cost=cost,
        parts_note=parts_note,
    )
    log = _append_log(machine, actor, values)
    if set_idle:
        apply_idle_transition(machine, actor)
    notify_maintenance_lifecycle(log, "logged")
    return log


@transaction.atomic
def create_schedule(machine, *, actor, description, interval_days, next_due, anchor="completion"):
    machine = lock_machine(machine, actor)
    prepare_machine(machine, actor, manage=True)
    schedule = MaintenanceSchedule.objects.create(
        machine=machine,
        description=clean_text(description, "description"),
        anchor=clean_anchor(anchor),
        interval_days=clean_interval(interval_days),
        next_due=_schedule_date(next_due),
        created_by=actor,
    )
    record(
        actor, "maintenance.schedule_created",
        makerspace=machine.makerspace, target=schedule,
        meta={"machine_id": machine.pk, "interval_days": schedule.interval_days},
    )
    notify_maintenance_lifecycle(schedule, "schedule_created")
    return schedule


@transaction.atomic
def update_schedule(schedule, *, actor, **changes):
    machine = lock_machine(schedule.machine, actor)
    prepare_machine(machine, actor, manage=True)
    schedule = rbac.scope_by_makerspace(
        actor, MaintenanceSchedule.objects.select_for_update(), makerspace_field="machine__makerspace_id",
    ).get(
        pk=schedule.pk, machine=machine,
    )
    allowed = {"description", "interval_days", "next_due", "anchor"}
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise ValidationError({name: "This field cannot be changed." for name in unknown})
    if not schedule.is_active:
        raise InactiveMaintenanceSchedule("Maintenance schedule is inactive.")
    if "anchor" in changes:
        schedule.anchor = clean_anchor(changes["anchor"])
    if "description" in changes:
        schedule.description = clean_text(changes["description"], "description")
    if "interval_days" in changes:
        schedule.interval_days = clean_interval(changes["interval_days"])
    if "next_due" in changes:
        schedule.next_due = _schedule_date(changes["next_due"])
    if changes:
        schedule.save(update_fields=[*changes.keys(), "updated_at"])
        record(
            actor, "maintenance.schedule_updated",
            makerspace=machine.makerspace, target=schedule,
            meta={"changed_fields": sorted(changes)},
        )
        notify_maintenance_lifecycle(schedule, "schedule_updated")
    return schedule


@transaction.atomic
def deactivate_schedule(schedule, *, actor):
    machine = lock_machine(schedule.machine, actor)
    prepare_machine(machine, actor, manage=True)
    schedule = rbac.scope_by_makerspace(
        actor, MaintenanceSchedule.objects.select_for_update(), makerspace_field="machine__makerspace_id",
    ).get(
        pk=schedule.pk, machine=machine,
    )
    if not schedule.is_active:
        return schedule
    schedule.is_active = False
    schedule.save(update_fields=["is_active", "updated_at"])
    record(
        actor, "maintenance.schedule_deactivated",
        makerspace=machine.makerspace, target=schedule,
        meta={"machine_id": machine.pk},
    )
    notify_maintenance_lifecycle(schedule, "schedule_deactivated")
    return schedule


@transaction.atomic
def complete_due(
    schedule, *, actor, summary, performed_at=None, cost=None,
    parts_note="", set_idle=False,
):
    machine = lock_machine(schedule.machine, actor)
    prepare_machine(machine, actor, manage=True)
    schedule = rbac.scope_by_makerspace(
        actor, MaintenanceSchedule.objects.select_for_update(), makerspace_field="machine__makerspace_id",
    ).get(
        pk=schedule.pk, machine=machine,
    )
    if not schedule.is_active:
        raise InactiveMaintenanceSchedule("Maintenance schedule is inactive.")
    ensure_idle_transition(machine, set_idle)
    values = validate_log_values(
        summary=summary, performed_at=performed_at, cost=cost,
        parts_note=parts_note,
    )
    old_due = schedule.next_due
    log = _append_log(machine, actor, values)
    schedule.next_due = next_due_after_completion(schedule, log.performed_at)
    schedule.save(update_fields=["next_due", "updated_at"])
    record(
        actor, "maintenance.schedule_completed",
        makerspace=machine.makerspace, target=schedule,
        meta={
            "log_id": log.pk,
            "anchor": schedule.anchor,
            "old_next_due": old_due.isoformat(),
            "new_next_due": schedule.next_due.isoformat(),
            "interval_days": schedule.interval_days,
        },
    )
    if set_idle:
        apply_idle_transition(machine, actor)
    notify_maintenance_lifecycle(
        schedule, "schedule_completed", log_id=log.pk
    )
    return log


def overdue_schedules(queryset=None, *, today=None):
    queryset = queryset if queryset is not None else MaintenanceSchedule.objects.all()
    today = timezone.localdate() if today is None else today
    return queryset.filter(is_active=True, next_due__lt=today).order_by(
        "next_due", "id",
    )


def _schedule_date(value):
    if isinstance(value, date) and not hasattr(value, "hour"):
        return value
    return clean_date(value)
