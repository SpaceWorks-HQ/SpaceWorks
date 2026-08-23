"""Idempotent recovery for every remote promotion crash boundary."""

import logging

from django.utils import timezone

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.artifact_ledger import (
    ArtifactLedgerMismatch,
    mark_cleanup_complete,
    mark_failed,
    mark_final_verified,
    mark_staging_verified,
)
from apps.backup.models import BackupArchive, BackupArtifactLedger, PlatformBackupSettings
from apps.backup.promotion import promote_verified_artifact


logger = logging.getLogger(__name__)


def reconcile_artifact_uploads(limit=50):
    ids = list(
        BackupArtifactLedger.objects.filter(
            state__in=(
                BackupArtifactLedger.State.PENDING,
                BackupArtifactLedger.State.STAGING_VERIFIED,
                BackupArtifactLedger.State.FINAL_VERIFIED,
            )
        )
        .order_by("created_at")
        .values_list("artifact_id", flat=True)[:limit]
    )
    reconciled = 0
    for artifact_id in ids:
        try:
            _reconcile_pending(artifact_id)
        except (ArtifactLedgerMismatch, storage.BackupVerificationError) as exc:
            logger.critical(
                "backup_artifact_reconciliation_failed",
                exc_info=True,
                extra={"artifact_id": str(artifact_id)},
            )
            _tombstone(artifact_id, exc)
        except Exception:
            logger.exception(
                "backup_artifact_reconciliation_retryable_failure",
                extra={"artifact_id": str(artifact_id)},
            )
        reconciled += 1
    for row in BackupArtifactLedger.objects.filter(
        state__in=(
            BackupArtifactLedger.State.AVAILABLE,
            BackupArtifactLedger.State.SUPERSEDED,
            BackupArtifactLedger.State.FAILED,
        ),
        cleanup_pending=True,
    ).order_by("created_at")[:limit]:
        staging_deleted = storage.delete_archive(row.staging_locator)
        final_deleted = (
            True
            if row.state != BackupArtifactLedger.State.FAILED
            else storage.delete_archive(row.final_locator)
        )
        if staging_deleted and final_deleted:
            mark_cleanup_complete(row.artifact_id)
    return reconciled


def _reconcile_pending(artifact_id):
    row = BackupArtifactLedger.objects.get(pk=artifact_id)
    final_exists = storage.object_exists(row.final_locator)
    staging_exists = storage.object_exists(row.staging_locator)
    if final_exists:
        final_size, final_sha256 = storage.stream_verify(
            row.final_locator,
            expected_size=row.expected_size_bytes,
            expected_sha256=row.outer_sha256,
        )
        mark_final_verified(row.artifact_id, final_size, final_sha256)
    elif staging_exists:
        staging_size, staging_sha256 = storage.stream_verify(
            row.staging_locator,
            expected_size=row.expected_size_bytes,
            expected_sha256=row.outer_sha256,
        )
        mark_staging_verified(row.artifact_id, staging_size, staging_sha256)
        storage.create_final_from_staging(row.staging_locator, row.final_locator)
        final_size, final_sha256 = storage.stream_verify(
            row.final_locator,
            expected_size=row.expected_size_bytes,
            expected_sha256=row.outer_sha256,
        )
        mark_final_verified(row.artifact_id, final_size, final_sha256)
    else:
        raise ArtifactLedgerMismatch(
            "The pending artifact has neither resumable staging nor final bytes."
        )
    # This is intentionally the exact same primitive used by the initial run.
    promote_verified_artifact(row.artifact_id)
    if storage.delete_archive(row.staging_locator):
        mark_cleanup_complete(row.artifact_id)


def _tombstone(artifact_id, exc):
    if not mark_failed(artifact_id, "reconciliation_mismatch"):
        return
    row = BackupArtifactLedger.objects.get(pk=artifact_id)
    storage.delete_archive(row.staging_locator)
    storage.delete_archive(row.final_locator)
    detail = str(exc).strip()[:500] or "Artifact reconciliation failed closed."
    archive = BackupArchive.objects.filter(pk=row.archive_uuid_snapshot).first()
    if archive and archive.status in {
        BackupArchive.Status.PENDING,
        BackupArchive.Status.RUNNING,
    }:
        BackupArchive.objects.filter(pk=archive.pk).update(
            status=BackupArchive.Status.FAILED,
            failure_detail=detail,
            completed_at=timezone.now(),
        )
        PlatformBackupSettings.objects.update_or_create(
            pk=1, defaults={"last_error": detail}
        )
        audit.record(
            archive.requested_by,
            "backup.archive_failed",
            target=archive,
            meta={"scope": archive.scope, "failure_detail": detail},
        )
