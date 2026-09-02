"""System checks for the private/public object-storage boundary."""

from django.conf import settings
from django.core.checks import Error, register

from config.storage_validation import BUCKET_COLLISION_MESSAGE, bucket_names_collide

from apps.evidence.retention_models import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS


@register()
def check_storage_bucket_separation(app_configs, **kwargs):
    if not bucket_names_collide(
        settings.AWS_STORAGE_BUCKET_NAME,
        settings.PUBLIC_IMAGE_BUCKET,
    ):
        return []
    return [
        Error(
            BUCKET_COLLISION_MESSAGE,
            id="evidence.E001",
        )
    ]


@register()
def check_evidence_retention_settings(app_configs, **kwargs):
    errors = []
    if not MIN_RETENTION_DAYS <= settings.EVIDENCE_OBJECT_RETENTION_DAYS <= MAX_RETENTION_DAYS:
        errors.append(
            Error(
                "EVIDENCE_OBJECT_RETENTION_DAYS must be between 30 and 3650.",
                id="evidence.E002",
            )
        )
    if not 1 <= settings.EVIDENCE_RETENTION_BATCH_SIZE <= 1000:
        errors.append(
            Error(
                "EVIDENCE_RETENTION_BATCH_SIZE must be between 1 and 1000.",
                id="evidence.E003",
            )
        )
    return errors
