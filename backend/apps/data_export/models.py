"""The source-deployment export job.

Model classification lives in :mod:`apps.data_export.classification`; it is re-exported
here because guards, datasets and the tenant-migration reference checks all import it
from ``apps.data_export.models``.
"""

import uuid

from django.conf import settings
from django.db import models

from .classification import (
    EXPORTED_MODEL_FIELDS,
    EXPORTED_MODELS,
    GLOBAL_MODELS,
    MODELS,
    NOT_TENANT_MODELS,
    OMITTED_MODELS,
)

__all__ = [
    "EXPORTED_MODEL_FIELDS",
    "EXPORTED_MODELS",
    "GLOBAL_MODELS",
    "MODELS",
    "NOT_TENANT_MODELS",
    "OMITTED_MODELS",
    "DataExportJob",
]


class DataExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"

    class FailureCode(models.TextChoices):
        NONE = "", "None"
        DEADLINE_EXCEEDED = "deadline_exceeded", "Deadline exceeded"
        INTEGRITY_ERROR = "integrity_error", "Integrity error"
        STORAGE_ERROR = "storage_error", "Storage error"
        QUOTA_EXCEEDED = "quota_exceeded", "Quota exceeded"
        INTERNAL_ERROR = "internal_error", "Internal error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="data_export_jobs"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="data_export_jobs"
    )
    fidelity = models.CharField(max_length=16, default="REDACTED")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    object_key = models.CharField(max_length=512, unique=True)
    accounted_size_bytes = models.PositiveBigIntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(
        max_length=32, choices=FailureCode.choices, blank=True, default=""
    )
    failure_detail = models.CharField(max_length=500, blank=True, default="")
    deadline_at = models.DateTimeField(null=True, blank=True)
    snapshot_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    download_token_digest = models.CharField(max_length=64, blank=True, default="")
    download_token_expires_at = models.DateTimeField(null=True, blank=True)
    download_token_consumed_at = models.DateTimeField(null=True, blank=True)
    download_issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issued_data_export_downloads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("makerspace", "status", "created_at"))]
    def __str__(self):
        return f"{self.makerspace_id}:{self.fidelity}:{self.status}"
