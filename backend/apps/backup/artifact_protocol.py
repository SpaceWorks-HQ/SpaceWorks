"""Backup-specific staged upload and verified final-object protocol."""

from apps.backup import storage
from apps.backup.artifact_ledger import (
    mark_cleanup_complete,
    mark_final_verified,
    mark_staging_verified,
    persist_pending,
)
from apps.backup.promotion import promote_verified_artifact


def upload_verify_and_promote(archive, build, size_bytes):
    ledger = persist_pending(archive, build, size_bytes)
    storage.upload_staging(ledger.staging_locator, build.encrypted)
    staging_size, staging_sha256 = storage.stream_verify(
        ledger.staging_locator,
        expected_size=ledger.expected_size_bytes,
        expected_sha256=ledger.outer_sha256,
    )
    mark_staging_verified(ledger.artifact_id, staging_size, staging_sha256)
    storage.create_final_from_staging(
        ledger.staging_locator, ledger.final_locator
    )
    final_size, final_sha256 = storage.stream_verify(
        ledger.final_locator,
        expected_size=ledger.expected_size_bytes,
        expected_sha256=ledger.outer_sha256,
    )
    mark_final_verified(ledger.artifact_id, final_size, final_sha256)
    promoted = promote_verified_artifact(ledger.artifact_id)
    if storage.delete_archive(ledger.staging_locator):
        mark_cleanup_complete(ledger.artifact_id)
    return promoted
