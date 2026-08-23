"""Durable Phase S capture and publication lineage for Lane D."""

import uuid

from django.conf import settings
from django.db import models


class TenantDumpCapture(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        CAPTURING = "capturing", "Capturing"
        CAPTURED = "captured", "Captured"
        DERIVING = "deriving", "Deriving"
        PENDING_PUBLICATION = "pending_publication", "Pending publication"
        PUBLISHED = "published", "Published"
        REFUSED = "refused", "Publication refused"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tenant_dump_captures",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_tenant_dump_captures",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.REQUESTED,
        db_index=True,
    )
    source_deployment_identity = models.JSONField(default=dict)
    source_makerspace_id = models.BigIntegerField()
    source_makerspace_slug = models.SlugField(max_length=100)
    superadmin_access_at_decision = models.BooleanField()
    frozen_tenant_recipients = models.JSONField(default=list)
    gate_owner_id = models.UUIDField(null=True, blank=True)
    gate_fencing_token = models.PositiveBigIntegerField(default=0)
    database_snapshot_at = models.DateTimeField(null=True, blank=True)
    source_postgres_major = models.PositiveSmallIntegerField(default=0)
    database_image_sha256 = models.CharField(max_length=64, blank=True)
    object_ledger = models.JSONField(default=list, blank=True)
    object_ledger_sha256 = models.CharField(max_length=64, blank=True)
    source_encryption_mode = models.BooleanField()
    catalog_digest = models.CharField(max_length=64)
    capture_completed_at = models.DateTimeField(null=True, blank=True)
    parent_database_sha256 = models.CharField(max_length=64, blank=True)
    parent_object_ledger_sha256 = models.CharField(max_length=64, blank=True)
    derivation_policy_sha256 = models.CharField(max_length=64, blank=True)
    content_ledger = models.JSONField(default=list, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    artifact_sha256 = models.CharField(max_length=64, blank=True)
    artifact_size_bytes = models.PositiveBigIntegerField(default=0)
    unpublished_object_key = models.CharField(max_length=512, blank=True)
    object_key = models.CharField(max_length=512, null=True, blank=True, unique=True)
    download_token_digest = models.CharField(max_length=64, blank=True)
    download_token_expires_at = models.DateTimeField(null=True, blank=True)
    download_token_consumed_at = models.DateTimeField(null=True, blank=True)
    refusal_code = models.CharField(max_length=64, blank=True)
    refusal_detail = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("makerspace", "status", "created_at"),
                name="tenant_dump_capture_idx",
            )
        ]
