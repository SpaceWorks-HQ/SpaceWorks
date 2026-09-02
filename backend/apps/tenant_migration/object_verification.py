"""Post-commit object checks required before target activation."""

import hmac

from apps.makerspaces.storage_key_collectors import (
    collect_private_object_keys,
    collect_public_image_keys,
)

from .insertion_errors import ImportVerificationError
from .models_import_objects import TenantImportObject
from . import object_storage


def verify_import_objects(job):
    if job.target_makerspace_id is None:
        raise ImportVerificationError("The import job has no committed target tenant.")
    rows = list(job.import_objects.order_by("pk"))
    verify_import_object_ownership(job, rows=rows)
    verify_import_object_journal_state(job)
    if not rows:
        return 0
    expected_staging = {row.staging_key for row in rows}
    actual_staging = object_storage.list_staging_keys(job.pk)
    if actual_staging != expected_staging:
        raise ImportVerificationError("The staging namespace is not fully journaled.")
    for row in rows:
        size, digest = object_storage.digest_object(row.bucket_kind, row.target_key)
        if size != row.size or not hmac.compare_digest(digest, row.sha256):
            raise ImportVerificationError(
                f"Pre-activation checksum mismatch for {row.source_key!r}."
            )
    return len(rows)


def verify_import_object_ownership(job, *, rows=None):
    rows = list(job.import_objects.order_by("pk")) if rows is None else rows
    target = job.target_makerspace
    owned = {
        (TenantImportObject.BucketKind.PRIVATE, key)
        for key in collect_private_object_keys(target, include_coordination=False)
    } | {
        (TenantImportObject.BucketKind.PUBLIC_IMAGE, key)
        for key in collect_public_image_keys(target, include_coordination=False)
    }
    expired_private = {
        (TenantImportObject.BucketKind.PRIVATE, key)
        for key in target.evidence_photos.filter(
            object_retention_state__status="expired"
        ).values_list("object_key", flat=True)
    }
    owned -= expired_private
    journal = {(row.bucket_kind, row.target_key) for row in rows}
    unowned = journal - owned
    missing = owned - journal
    if unowned:
        raise ImportVerificationError(
            f"Promoted object has no committed owner row: {sorted(unowned)[0][1]!r}."
        )
    if missing:
        raise ImportVerificationError(
            f"Committed row names an unpromoted object: {sorted(missing)[0][1]!r}."
        )


def verify_import_object_journal_state(job):
    invalid = job.import_objects.exclude(state=TenantImportObject.State.VERIFIED)
    if invalid.exists():
        row = invalid.order_by("pk").first()
        raise ImportVerificationError(
            f"Object journal is not activation-ready: {row.source_key!r} is {row.state}."
        )
