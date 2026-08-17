"""Durable journal for target-side tenant object promotion and rollback."""

from django.db import models

from .models_import_job import TenantImportJob


class TenantImportObject(models.Model):
    class BucketKind(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC_IMAGE = "public_image", "Public image"

    class State(models.TextChoices):
        STAGED = "staged", "Staged"
        PROMOTED = "promoted", "Promoted"
        VERIFIED = "verified", "Verified"
        FAILED = "failed", "Failed"
        ROLLED_BACK = "rolled_back", "Rolled back"

    job = models.ForeignKey(
        TenantImportJob,
        on_delete=models.CASCADE,
        related_name="import_objects",
    )
    bucket_kind = models.CharField(max_length=16, choices=BucketKind.choices)
    source_key = models.CharField(max_length=1024)
    staging_key = models.CharField(max_length=1024)
    target_key = models.CharField(max_length=1024)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.STAGED,
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    quota_charged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("job", "source_key"),
                name="uniq_timport_object_source",
            )
        ]
        indexes = [
            models.Index(fields=("job", "state"), name="timport_obj_job_state_idx"),
            models.Index(fields=("state", "updated_at"), name="timport_obj_state_time_idx"),
        ]
