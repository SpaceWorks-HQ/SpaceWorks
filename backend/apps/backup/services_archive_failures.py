"""Holder-fenced archive failure transitions and stale-promotion cleanup."""

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.artifact_ledger import ArtifactLedgerMismatch, mark_failed
from apps.backup.archive_builder import BackupBuildError
from apps.backup.models import BackupArchive, BackupArtifactLedger, PlatformBackupSettings
from apps.backup.operation_lock import OperationLockUnavailable


logger = logging.getLogger(__name__)


def _fail_archive(
    archive_or_id, holder_or_detail, detail=None, *, expected_status=None
):
    if isinstance(archive_or_id, BackupArchive):
        archive = archive_or_id
        holder = archive.build_holder
        message = holder_or_detail
        expected_status = expected_status or archive.status
        archive_id = archive.pk
    else:
        archive_id = archive_or_id
        holder = holder_or_detail
        message = detail
    won, cleanup = _commit_archive_failed(
        archive_id, holder, message, expected_status=expected_status
    )
    if not won:
        return False
    for key in cleanup:
        storage.delete_archive(key)
    if holder is not None or cleanup:
        storage.delete_archive_prefix(_staging_prefix(archive_id))
    return True


@transaction.atomic
def _commit_archive_failed(archive_id, holder, detail, *, expected_status):
    holder_filter = (
        {"build_holder": holder}
        if holder is not None
        else {"build_holder__isnull": True}
    )
    archive = BackupArchive.objects.select_for_update().filter(
        pk=archive_id, status=expected_status, **holder_filter
    ).first()
    if archive is None:
        return False, ()
    ledger = BackupArtifactLedger.objects.select_for_update().filter(
        pk=archive.pk
    ).first()
    protected = {
        BackupArtifactLedger.State.AVAILABLE,
        BackupArtifactLedger.State.SUPERSEDED,
        BackupArtifactLedger.State.BYTES_DELETED,
        BackupArtifactLedger.State.FINAL_VERIFIED,
    }
    if ledger and ledger.state in protected:
        return False, ()
    if ledger:
        mark_failed(ledger.artifact_id, "archive_run_failed")
    message = str(detail).strip()[:500]
    archive.status = BackupArchive.Status.FAILED
    archive.failure_detail = message
    archive.completed_at = timezone.now()
    archive.download_token_digest = ""
    archive.download_token_expires_at = None
    archive.save()
    PlatformBackupSettings.objects.update_or_create(
        pk=1, defaults={"last_error": message}
    )
    audit.record(
        archive.requested_by,
        "backup.archive_failed",
        makerspace=archive.makerspace,
        target=archive,
        meta={"scope": archive.scope, "failure_detail": message},
    )
    cleanup = (
        (ledger.staging_locator, ledger.final_locator)
        if ledger
        else ((archive.object_key,) if holder is not None else ())
    )
    return True, cleanup


def fail_archive_dispatch(archive, exc):
    logger.exception(
        "backup_archive_dispatch_failed",
        exc_info=exc,
        extra={"archive_id": str(archive.pk)},
    )
    return _fail_archive(
        archive.pk,
        None,
        "The backup worker could not accept the job.",
        expected_status=BackupArchive.Status.PENDING,
    )


def sweep_stale_promotions(*, batch_size=100):
    stale = list(
        BackupArchive.objects.filter(status=BackupArchive.Status.PROMOTING)
        .order_by("pk")
        .values_list("pk", "build_holder")[:batch_size]
    )
    return sum(
        bool(
            _fail_archive(
                archive_id,
                holder,
                "The backup promotion owner exited before finalization.",
                expected_status=BackupArchive.Status.PROMOTING,
            )
        )
        for archive_id, holder in stale
    )


def _staging_prefix(archive_id):
    return f"backup-archives/staging/{archive_id}/"


def _safe_failure_detail(exc):
    if isinstance(
        exc,
        (
            BackupBuildError,
            storage.BackupStorageError,
            ArtifactLedgerMismatch,
            OperationLockUnavailable,
        ),
    ):
        return str(exc)[:500]
    return "The backup failed unexpectedly; inspect server logs."
