"""Durable Lane E artifact and component custody records."""

from django.db import models


class B1ActivationState(models.Model):
    class State(models.TextChoices):
        ON = "on", "Platform readable"
        OFF_PENDING = "off_pending", "Exclusion pending"
        OFF_EFFECTIVE = "off_effective", "Exclusion effective"

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="b1_activation_state",
    )
    state = models.CharField(max_length=16, choices=State.choices)
    effective_artifact_id = models.UUIDField(null=True, blank=True)
    effective_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state__in=("on", "off_pending"),
                        effective_artifact_id__isnull=True,
                        effective_at__isnull=True,
                    )
                    | models.Q(
                        state="off_effective",
                        effective_artifact_id__isnull=False,
                        effective_at__isnull=False,
                    )
                ),
                name="backup_b1_activation_effective_facts",
            )
        ]


class BackupArtifactLedger(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending upload"
        STAGING_VERIFIED = "staging_verified", "Staging verified"
        FINAL_VERIFIED = "final_verified", "Final verified"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"
        SUPERSEDED = "superseded", "Superseded"
        BYTES_DELETED = "bytes_deleted", "Managed bytes deleted"

    artifact_id = models.UUIDField(primary_key=True, editable=False)
    capture_id = models.UUIDField(unique=True, editable=False)
    archive = models.OneToOneField(
        "backup.BackupArchive",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artifact_ledger",
    )
    archive_uuid_snapshot = models.UUIDField(unique=True, editable=False)
    outer_sha256 = models.CharField(max_length=64)
    outer_manifest_sha256 = models.CharField(max_length=64)
    format = models.CharField(max_length=80)
    outer_manifest = models.JSONField()
    frozen_promotion_snapshot = models.JSONField()
    expected_size_bytes = models.PositiveBigIntegerField()
    staging_locator = models.CharField(max_length=512, unique=True)
    final_locator = models.CharField(max_length=512, unique=True)
    state = models.CharField(
        max_length=24, choices=State.choices, default=State.PENDING
    )
    predecessor_artifact_id_snapshot = models.UUIDField(null=True, blank=True)
    predecessor_success_at_snapshot = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    staging_verified_at = models.DateTimeField(null=True, blank=True)
    staging_verified_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    staging_verified_sha256 = models.CharField(max_length=64, blank=True)
    final_verified_at = models.DateTimeField(null=True, blank=True)
    final_verified_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    final_verified_sha256 = models.CharField(max_length=64, blank=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    bytes_deleted_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    cleanup_pending = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("state", "created_at"),
                name="backup_art_state_created_idx",
            )
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Backup artifact ledger rows are durable and cannot be deleted.")


class BackupArtifactComponent(models.Model):
    class Kind(models.TextChoices):
        MAIN = "main", "Readable main"
        SLICE = "slice", "Sovereign slice"

    class StorageState(models.TextChoices):
        PENDING = "pending", "Pending"
        AVAILABLE = "available", "Available"
        BYTES_DELETED = "bytes_deleted", "Managed bytes deleted"

    artifact = models.ForeignKey(
        BackupArtifactLedger, on_delete=models.PROTECT, related_name="components"
    )
    component_id = models.UUIDField(unique=True, editable=False)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    makerspace_id_snapshot = models.BigIntegerField(null=True, blank=True)
    ciphertext_path = models.CharField(max_length=512)
    ciphertext_sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveBigIntegerField()
    storage_state = models.CharField(
        max_length=16,
        choices=StorageState.choices,
        default=StorageState.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    available_at = models.DateTimeField(null=True, blank=True)
    bytes_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("artifact_id", "kind", "makerspace_id_snapshot", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("artifact", "kind", "makerspace_id_snapshot"),
                name="uniq_backup_artifact_component",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="main", makerspace_id_snapshot__isnull=True)
                    | models.Q(kind="slice", makerspace_id_snapshot__isnull=False)
                ),
                name="backup_component_kind_matches_tenant",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Backup artifact components cannot be deleted.")


class BackupComponentRecipient(models.Model):
    component = models.ForeignKey(
        BackupArtifactComponent,
        on_delete=models.PROTECT,
        related_name="recipient_associations",
    )
    fingerprint = models.CharField(max_length=64)
    associated_at = models.DateTimeField(auto_now_add=True)
    tombstoned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("component_id", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("component", "fingerprint"),
                name="uniq_backup_component_recipient",
            )
        ]

    def delete(self, *args, **kwargs):
        raise RuntimeError("Recipient-use history is tombstoned, never deleted.")


# Importing this module from backup.models registers the operational singleton with
# Django without growing the already-over-ceiling models.py barrel.
from .models_host_identity import DeploymentDatabaseIdentity  # noqa: E402,F401
