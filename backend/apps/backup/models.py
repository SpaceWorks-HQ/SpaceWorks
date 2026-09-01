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
        PROMOTING = "promoting", "Promoting"
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
    backup_run = models.ForeignKey(
        "backup.BackupRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archives",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    build_holder = models.UUIDField(null=True, blank=True)
    object_key = models.CharField(max_length=512, unique=True)
    staging_object_key = models.CharField(max_length=512, null=True, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    archive_sha256 = models.CharField(max_length=64, blank=True)
    age_encrypted = models.BooleanField(default=False)
    failure_detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
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
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="available")
                    | models.Q(expires_at__isnull=False)
                ),
                name="backup_available_requires_expiry",
            ),
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



# Stable public model imports; restore, custody and artifact implementations stay split out.
from .models_restore import (  # noqa: E402,F401
    BackupLease,
    DeploymentRecoveryState,
    RestoreOperation,
    RestoreRollbackObject,
)
from .models_custody_alarm import ArchiveCustodyAlarmDelivery  # noqa: E402,F401
from .models_artifact_ledger import B1ActivationState, BackupArtifactComponent, BackupArtifactLedger, BackupComponentRecipient  # noqa: E402,F401
from .models_tenant_exit_custody import (  # noqa: E402,F401
    MakerspaceTenantExitCustodyState,
    TenantExitCustodyAlarmDelivery,
)
from .models_restore_reservations import (  # noqa: E402,F401
    B1FenceContinuity,
    B1ReservationEntry,
    B1RestoreComponentState,
    B1RestoreOperationState,
)
from .models_runs import BackupRun, BackupRunCoverage  # noqa: E402,F401
