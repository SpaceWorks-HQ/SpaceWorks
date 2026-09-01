"""Fail-closed validation for storage settings shared by every process type."""

from django.core.exceptions import ImproperlyConfigured


BUCKET_COLLISION_MESSAGE = (
    "PUBLIC_IMAGE_BUCKET must differ from AWS_STORAGE_BUCKET_NAME; the public "
    "bucket policy must never apply to private evidence or documents."
)


def bucket_names_collide(private_bucket, public_bucket):
    private_name = str(private_bucket or "").strip().casefold()
    public_name = str(public_bucket or "").strip().casefold()
    return private_name == public_name


def assert_distinct_storage_buckets(private_bucket, public_bucket):
    if bucket_names_collide(private_bucket, public_bucket):
        raise ImproperlyConfigured(BUCKET_COLLISION_MESSAGE)
