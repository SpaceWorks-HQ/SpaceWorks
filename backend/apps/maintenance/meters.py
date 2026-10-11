"""Meter due state is derived from immutable usage since the last completion."""

from decimal import Decimal
from django.db.models import Sum, Count, OuterRef, Subquery, Q, DecimalField, Value, IntegerField, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.makerspaces.platform import feature_enabled
from apps.machines.models import MachineUsageEntry
from .meter_jobs import runs, scoped_runs


def meter_rows(schedule):
    return rbac.scope_verified_tenant(MachineUsageEntry.objects.all(),
        schedule.machine.makerspace, field="machine__makerspace_id",
    ).filter(machine_id=schedule.machine_id, created_at__gte=schedule.meter_started_at,
             service_request__isnull=True)


def readings(schedule):
    rows = meter_rows(schedule)
    # One usage entry per run; generic manual hour entries are not completed jobs.
    service = scoped_runs(schedule)
    minutes = service.aggregate(total=Sum("actual_minutes"))["total"] or 0
    return {"hours": (rows.aggregate(total=Sum("hours"))["total"] or Decimal("0")) + Decimal(minutes)/60,
            "jobs": rows.filter(source=MachineUsageEntry.Source.TYPED_MANUAL).count() + service.count()}


def meter_due(schedule):
    if schedule.trigger == "days" or not feature_enabled(schedule.machine.makerspace, "maintenance.meters"):
        return False
    value = readings(schedule)
    return bool((schedule.usage_hours is not None and value["hours"] >= schedule.usage_hours)
                or (schedule.job_count is not None and value["jobs"] >= schedule.job_count))


def due(schedule, today):
    return schedule.is_active and ((schedule.trigger in ("days", "both") and schedule.next_due <= today)
                                   or meter_due(schedule))


def due_queryset(queryset, today):
    """Filter before pagination so non-due schedules cannot starve a meter batch."""
    rows = MachineUsageEntry.objects.filter(machine_id=OuterRef("machine_id"),
                                            created_at__gte=OuterRef("meter_started_at"),
                                            service_request__isnull=True)
    hours = rows.order_by().values("machine_id").annotate(total=Sum("hours")).values("total")
    jobs = rows.filter(source=MachineUsageEntry.Source.TYPED_MANUAL).order_by().values("machine_id").annotate(total=Count("pk")).values("total")
    service = runs(OuterRef("machine_id"), OuterRef("meter_started_at")).order_by().values("assigned_machine_id")
    minutes = service.annotate(total=Sum("actual_minutes")).values("total")
    service_jobs = service.annotate(total=Count("pk")).values("total")
    queryset = queryset.annotate(
        logged_hours=Coalesce(Subquery(hours), Value(Decimal("0")), output_field=DecimalField(max_digits=12, decimal_places=2)),
        service_hours=Coalesce(Subquery(minutes), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2))/Value(Decimal("60")),
        meter_jobs=Coalesce(Subquery(jobs), Value(0), output_field=IntegerField()) + Coalesce(Subquery(service_jobs), Value(0), output_field=IntegerField()),
    ).annotate(
        meter_hours=F("logged_hours") + F("service_hours"),
    )
    calendar = Q(trigger__in=("days", "both"), next_due__lt=today)
    usage = Q(trigger__in=("usage", "both")) & (
        Q(usage_hours__isnull=False, meter_hours__gte=F("usage_hours")) |
        Q(job_count__isnull=False, meter_jobs__gte=F("job_count"))
    )
    # Archived feature-off spaces retain calendar schedules but no meter behavior.
    return queryset.filter(calendar | (usage & Q(machine__makerspace__enabled_features__contains=["maintenance.meters"])))


def validate_meter(schedule):
    if schedule.trigger not in ("days", "usage", "both"):
        raise ValidationError({"trigger": "Choose days, usage or both."})
    if schedule.trigger != "days":
        if not feature_enabled(schedule.machine.makerspace, "maintenance.meters"):
            raise ValidationError({"trigger": "Usage-based maintenance is disabled."})
        if schedule.usage_hours is None and schedule.job_count is None:
            raise ValidationError({"trigger": "A positive hours or jobs threshold is required."})
    for field in ("usage_hours", "job_count"):
        value = getattr(schedule, field)
        if value is not None and (isinstance(value, bool) or value <= 0):
            raise ValidationError({field: "Enter a positive threshold."})


def completed_meter(schedule, performed_at):
    # Server completion time prevents a backdated maintenance log recounting old use.
    schedule.meter_started_at = timezone.now()
