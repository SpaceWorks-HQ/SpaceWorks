"""Deployment restore, recovery and rollback state.

Split from the archive-side models so each file keeps one lifecycle.  These classes are
re-exported from :mod:`apps.backup.models`, which stays the app's public model surface.
"""

import uuid

from django.conf import settings
from django.db import models


class RestoreOperation(models.Model):
    class Kind(models.TextChoices):
        ROLLBACK_IN_PLACE = "rollback_in_place", "Rollback in place"
        DISASTER = "disaster", "Disaster or cross-server"

    class Stage(models.TextChoices):
        REQUESTED = "requested", "Requested"
        CLAIMED = "claimed", "Claimed"
        PREFLIGHT = "preflight", "Preflight"
        QUIESCED = "quiesced", "Quiesced"
        DB_RESTORING = "db_restoring", "Database restoring"
        OBJECTS_RESTORING = "objects_restoring", "Objects restoring"
        VALIDATING = "validating", "Validating"
        COMPLETED = "completed", "Completed"
        RESTORED_QUARANTINED = "restored_quarantined", "Restored quarantined"
        ROLLING_BACK = "rolling_back", "Rolling back"
        FAILED = "failed", "Failed"
        ABORTED = "aborted", "Aborted"

    class Decision(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCEED = "proceed", "Proceed"
        RESET = "reset", "Proceed with authority reset"
        ABORT = "abort", "Abort"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    archive = models.ForeignKey(
        "backup.BackupArchive", on_delete=models.PROTECT, related_name="restores"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    stage = models.CharField(max_length=24, choices=Stage.choices, default=Stage.REQUESTED)
    decision = models.CharField(max_length=16, choices=Decision.choices, default=Decision.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="requested_restores",
    )
    requested_by_username_snapshot = models.CharField(max_length=150, blank=True)
    fencing_token = models.UUIDField(null=True, blank=True, unique=True)
    restore_diff = models.JSONField(default=dict, blank=True)
    decision_deadline_at = models.DateTimeField(null=True, blank=True)
    supervisor_heartbeat_at = models.DateTimeField(null=True, blank=True)
    error_detail = models.CharField(max_length=500, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-requested_at",)


class DeploymentRecoveryState(models.Model):
    class Mode(models.TextChoices):
        NORMAL = "normal", "Normal"
        TARGET_IMPORT = "target_import", "Target import"
        QUIESCED = "quiesced", "Quiesced"
        QUARANTINED = "quarantined", "Quarantined"

    mode = models.CharField(max_length=16, choices=Mode.choices, default=Mode.NORMAL)
    auth_generation = models.UUIDField(default=uuid.uuid4, editable=False)
    active_restore = models.ForeignKey(
        RestoreOperation, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recovery_states",
    )
    recovery_principal = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="recovery_principal_states",
    )
    quarantine_reason = models.TextField(blank=True)
    quarantined_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="acknowledged_recovery_states",
    )
    acknowledgement = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def __str__(self):
        return f"Deployment recovery state ({self.mode})"


class BackupLease(models.Model):
    name = models.CharField(max_length=64, unique=True)
    holder = models.UUIDField(null=True, blank=True)
    leased_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class RestoreRollbackObject(models.Model):
    class BucketKind(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC_IMAGE = "public_image", "Public image"

    restore = models.ForeignKey(RestoreOperation, on_delete=models.CASCADE, related_name="rollback_objects")
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="restore_rollback_objects",
    )
    bucket_kind = models.CharField(max_length=16, choices=BucketKind.choices)
    module_key = models.CharField(max_length=64, blank=True)
    source_key = models.CharField(max_length=1024)
    copy_key = models.CharField(max_length=1024, blank=True)
    source_was_absent = models.BooleanField(default=False)
    source_absent_marker_version_id = models.CharField(max_length=512, blank=True)
    source_version_id = models.CharField(max_length=512, blank=True)
    replacement_version_id = models.CharField(max_length=512, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("restore", "bucket_kind", "source_key"),
                name="uniq_restore_rollback_object",
            )
        ]
