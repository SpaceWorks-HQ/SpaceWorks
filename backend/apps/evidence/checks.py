"""System checks for the private/public object-storage boundary."""

from django.conf import settings
from django.core.checks import Error, register

from config.storage_validation import BUCKET_COLLISION_MESSAGE, bucket_names_collide


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
