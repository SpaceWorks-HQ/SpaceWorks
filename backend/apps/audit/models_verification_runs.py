"""Immutable staff verification runs and their append-only status/result events.

The same shape as signing-key rotation: an immutable root that records exactly what was
asked (the normalized filter snapshot and the highest audit row id it covers), plus
append-only events that carry state and aggregate coverage. Status is derived from the
latest event; nothing is ever updated in place. No actor label, raw metadata, exception
text, MAC material or anchor payload is persisted -- only closed codes and counts.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditVerificationRun(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="audit_verification_runs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_verification_runs",
    )
    action_filter = models.CharField(max_length=100, blank=True)
    target_type_filter = models.CharField(max_length=200, blank=True)
    target_id_filter = models.CharField(max_length=100, blank=True)
    # A filter VALUE, not a relation: any positive id is valid and may select zero rows,
    # and it must never stop a user from being deleted.
    actor_filter = models.PositiveBigIntegerField(null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    snapshot_max_id = models.PositiveBigIntegerField()
    filter_fingerprint = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["makerspace", "-created_at"], name="audit_vrun_space_created"),
            models.Index(fields=["makerspace", "filter_fingerprint"], name="audit_vrun_space_fp"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(actor_filter__isnull=True) | models.Q(actor_filter__gt=0),
                name="ck_audit_vrun_actor_filter_positive",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("AuditVerificationRun rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditVerificationRun rows are immutable.")


class AuditVerificationRunEvent(models.Model):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        RETRYING = "RETRYING", "Retrying"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        INCOMPLETE = "INCOMPLETE", "Incomplete"
        FAILED = "FAILED", "Failed"
        TIMED_OUT = "TIMED_OUT", "Timed out"

    class ChainStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        LOCALLY_VERIFIED = "locally_verified", "Locally verified"
        INVALID = "invalid", "Invalid"
        UNAVAILABLE = "unavailable", "Unavailable"

    class AnchorStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        NOT_CONFIGURED = "not_configured", "Not configured"
        EXTERNALLY_ANCHORED = "externally_anchored", "Externally anchored"
        INVALID = "invalid", "Invalid"
        UNAVAILABLE = "unavailable", "Unavailable"

    class FailureCode(models.TextChoices):
        NONE = "", "None"
        ANCHOR_RETRY_EXHAUSTED = "anchor_retry_exhausted", "Anchor retry exhausted"
        VERIFICATION_UNAVAILABLE = "verification_unavailable", "Verification unavailable"
        VERIFICATION_BOUNDS_EXCEEDED = "verification_bounds_exceeded", "Bounds exceeded"
        DATABASE_RETRY_EXHAUSTED = "database_retry_exhausted", "Database retry exhausted"
        TASK_ERROR = "task_error", "Task error"
        SOFT_TIME_LIMIT = "soft_time_limit", "Soft time limit"
        STALE_RUN = "stale_run", "Stale run"

    run = models.ForeignKey(AuditVerificationRun, on_delete=models.CASCADE, related_name="events")
    state = models.CharField(max_length=16, choices=State.choices)
    attempt = models.PositiveSmallIntegerField(default=0)
    row_count = models.PositiveIntegerField(default=0)
    mac_valid_count = models.PositiveIntegerField(default=0)
    unattested_count = models.PositiveIntegerField(default=0)
    mac_invalid_count = models.PositiveIntegerField(default=0)
    mac_unavailable_count = models.PositiveIntegerField(default=0)
    unbatched_count = models.PositiveIntegerField(default=0)
    local_batch_verified_count = models.PositiveIntegerField(default=0)
    batch_invalid_count = models.PositiveIntegerField(default=0)
    batch_unavailable_count = models.PositiveIntegerField(default=0)
    externally_anchored_count = models.PositiveIntegerField(default=0)
    chain_status = models.CharField(
        max_length=24, choices=ChainStatus.choices, default=ChainStatus.PENDING
    )
    anchor_status = models.CharField(
        max_length=24, choices=AnchorStatus.choices, default=AnchorStatus.PENDING
    )
    failure_code = models.CharField(
        max_length=32, choices=FailureCode.choices, blank=True, default=""
    )
    first_audit_log_id = models.PositiveBigIntegerField(null=True, blank=True)
    first_batch_seq = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    TERMINAL_STATES = frozenset({"SUCCEEDED", "INCOMPLETE", "FAILED", "TIMED_OUT"})
    ACTIVE_STATES = frozenset({"QUEUED", "RUNNING", "RETRYING"})

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["run", "-id"], name="audit_vrun_event_latest")]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("AuditVerificationRunEvent rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("AuditVerificationRunEvent rows are append-only.")
