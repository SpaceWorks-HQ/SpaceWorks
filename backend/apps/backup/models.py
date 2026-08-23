import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


ARCHIVE_PURGE_WARNING = (
    "Downloaded backup archives are outside makerspace purge guarantees. "
    "Delete retained copies separately when they are no longer required."
)


class PlatformBackupSettings(models.Model):
    automatic_backups_enabled = models.BooleanField(default=False)
    retention_days = models.PositiveSmallIntegerField(
        default=30, validators=(MinValueValidator(1), MaxValueValidator(3650))
    )
    last_scheduled_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def __str__(self):
        return "Platform backup settings"


class BackupArchive(models.Model):
    class Scope(models.TextChoices):
        DEPLOYMENT = "deployment", "Full deployment"
        MAKERSPACE = "makerspace", "Makerspace"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=16, choices=Scope.choices)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="backup_archives",
    )
    superadmin_access_at_decision = models.BooleanField(null=True)
    legacy_pre_decision_snapshot = models.BooleanField(default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="requested_backup_archives",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    object_key = models.CharField(max_length=512, unique=True)
    manifest = models.JSONField(default=dict, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    archive_sha256 = models.CharField(max_length=64, blank=True)
    age_encrypted = models.BooleanField(default=False)
    failure_detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    download_token_digest = models.CharField(max_length=64, blank=True)
    download_token_expires_at = models.DateTimeField(null=True, blank=True)
    download_token_consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("scope", "makerspace", "status", "created_at"))]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(scope="makerspace")
                    | models.Q(superadmin_access_at_decision__isnull=False)
                    | models.Q(legacy_pre_decision_snapshot=True)
                ),
                name="backup_makerspace_decision_snapshot_present",
            )
        ]


class MakerspaceArchiveRecipient(models.Model):
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="archive_recipients",
    )
    public_recipient = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=64)
    label = models.CharField(max_length=120)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="added_archive_recipients",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    compromised_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    challenge_nonce_digest = models.CharField(max_length=64, blank=True)
    challenge_issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("pk",)


class MakerspaceArchiveCustodyState(models.Model):
    class State(models.TextChoices):
        HEALTHY = "healthy", "Healthy"
        NOT_APPLICABLE = "not_applicable", "Not applicable"
        DEGRADED_ONE_RECIPIENT = (
            "degraded_one_recipient",
            "Degraded: one recipient",
        )
        FLOOR_BREACHED_ZERO = "floor_breached_zero", "Floor breached: zero"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="archive_custody_state",
    )
    state = models.CharField(
        max_length=32,
        choices=State.choices,
        default=State.HEALTHY,
    )
    reason_code = models.CharField(max_length=64, blank=True)
    entered_at = models.DateTimeField(default=timezone.now)
    cleared_at = models.DateTimeField(null=True, blank=True)
    last_alarm_at = models.DateTimeField(null=True, blank=True)
    triggering_recipient = models.ForeignKey(
        MakerspaceArchiveRecipient,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="triggered_custody_states",
    )
    alarm_episode = models.PositiveBigIntegerField(default=0)
    alarm_revision = models.PositiveBigIntegerField(default=0)


class ArchiveRecipientReservation(models.Model):
    class Kind(models.TextChoices):
        TENANT = "tenant", "Tenant"
        PLATFORM = "platform", "Platform"

    fingerprint = models.CharField(max_length=64, unique=True)
    makerspace_id_snapshot = models.BigIntegerField(null=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    reserved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind="tenant", makerspace_id_snapshot__isnull=False)
                    | models.Q(kind="platform", makerspace_id_snapshot__isnull=True)
                ),
                name="archive_reservation_kind_matches_tenant",
            )
        ]


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
    archive = models.ForeignKey(BackupArchive, on_delete=models.PROTECT, related_name="restores")
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


# Keep the public model import surface stable while the custody outbox lives in its
# own module; this file is already at the repository's size ceiling.
from .models_custody_alarm import ArchiveCustodyAlarmDelivery  # noqa: E402,F401
from .models_tenant_exit_custody import (  # noqa: E402,F401
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
