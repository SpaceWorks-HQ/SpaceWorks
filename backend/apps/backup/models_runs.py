import uuid

from django.db import models
from django.db.models import Q


class BackupRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cohort_at = models.DateTimeField()
    flag_snapshot = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    failure_detail = models.CharField(max_length=500, blank=True)
    holder = models.UUIDField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "backup"
        constraints = [
            models.UniqueConstraint(
                models.Value(1),
                condition=Q(status__in=("pending", "running")),
                name="uniq_open_backup_run",
            )
        ]


class BackupRunCoverage(models.Model):
    class Path(models.TextChoices):
        GLOBAL = "global", "Global"
        TENANT = "tenant", "Tenant"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        COVERED = "covered", "Covered"

    run = models.ForeignKey(
        BackupRun, on_delete=models.CASCADE, related_name="coverage_rows"
    )
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="backup_run_coverages",
    )
    archive = models.ForeignKey(
        "backup.BackupArchive",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="run_coverages",
    )
    path = models.CharField(max_length=16, choices=Path.choices)
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.PENDING
    )
    makerspace_id_snapshot = models.BigIntegerField()
    archive_id_snapshot = models.UUIDField(null=True, blank=True)
    archive_sha256_snapshot = models.CharField(max_length=64, blank=True)
    completed_at_snapshot = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "backup"
        constraints = [
            models.UniqueConstraint(
                fields=("run", "makerspace_id_snapshot"),
                name="uniq_backup_run_makerspace_coverage",
            )
        ]
