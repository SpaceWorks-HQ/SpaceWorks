from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


from .models_feed import MaintenanceCalendarFeed  # noqa: F401


class MaintenanceLogImmutableError(RuntimeError):
    pass


class MaintenanceSchedule(models.Model):
    trigger = models.CharField(max_length=8, choices=[("days", "Days"), ("usage", "Usage"), ("both", "Days or usage")], default="days")
    usage_hours = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    job_count = models.PositiveIntegerField(null=True, blank=True)
    meter_started_at = models.DateTimeField(default=timezone.now, editable=False)
    class Anchor(models.TextChoices):
        COMPLETION = "completion", "Completion date"
        CALENDAR = "calendar", "Fixed calendar"

    anchor = models.CharField(max_length=16, choices=Anchor.choices, default=Anchor.COMPLETION)
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.CASCADE,
        related_name="maintenance_schedules",
    )
    description = models.TextField()
    interval_days = models.PositiveIntegerField()
    next_due = models.DateField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_due", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(trigger__in=["days", "usage", "both"]), name="maintenance_trigger_valid"),
            models.CheckConstraint(condition=Q(usage_hours__isnull=True) | Q(usage_hours__gt=0), name="maintenance_usage_positive"),
            models.CheckConstraint(condition=Q(job_count__isnull=True) | Q(job_count__gt=0), name="maintenance_jobs_positive"),
            models.CheckConstraint(condition=Q(trigger="days") | Q(usage_hours__isnull=False) | Q(job_count__isnull=False), name="maintenance_meter_required"),
            models.CheckConstraint(condition=Q(anchor__in=["completion", "calendar"]),
                                   name="maintenance_anchor_valid"),
            models.CheckConstraint(
                condition=Q(interval_days__gt=0),
                name="maintenance_interval_days_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["machine", "is_active", "next_due"],
                name="maintenance_due_lookup_idx",
            ),
        ]

    def __str__(self):
        return f"{self.machine}: {self.description}"


class MaintenanceLog(models.Model):
    machine = models.ForeignKey(
        "machines.Machine",
        on_delete=models.CASCADE,
        related_name="maintenance_logs",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.PROTECT, related_name="+",
    )
    performed_at = models.DateTimeField(default=timezone.now)
    summary = models.TextField()
    cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    parts_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cost__isnull=True) | Q(cost__gte=0),
                name="maintenance_log_cost_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["machine", "performed_at"],
                name="maintenance_log_machine_time_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise MaintenanceLogImmutableError("MaintenanceLog rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise MaintenanceLogImmutableError("MaintenanceLog rows are append-only.")

    def __str__(self):
        return f"{self.machine} @ {self.performed_at:%Y-%m-%d %H:%M:%S}"


class MaintenanceLogDocument(models.Model):
    log = models.ForeignKey(
        MaintenanceLog,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    object_key = models.CharField(max_length=500, unique=True)
    size_bytes = models.PositiveBigIntegerField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.object_key
