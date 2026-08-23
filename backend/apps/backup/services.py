import logging
import os
from datetime import timedelta
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.artifact_ledger import ArtifactLedgerMismatch, mark_failed
from apps.backup.artifact_protocol import upload_verify_and_promote
from apps.backup.archive_builder import BackupBuildError, build_archive
from apps.backup.archive_import import import_disaster_archive
from apps.backup.models import (
    BackupArchive,
    BackupArtifactLedger,
    BackupLease,
    PlatformBackupSettings,
)
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
from apps.makerspaces.models import Makerspace


logger = logging.getLogger(__name__)

from apps.backup.services_access import (  # noqa: E402,F401
    DownloadTokenError,
    consume_download_token,
    issue_download_token,
    purge_expired_archives,
)


def superadmin_access_decision(makerspace):
    """Return the request-time decision from an already locked makerspace row."""
    return makerspace.superadmin_access_enabled


def create_archive(actor, *, scope, makerspace=None):
    if scope == BackupArchive.Scope.DEPLOYMENT and makerspace is not None:
        raise ValidationError("A deployment archive cannot be scoped to a makerspace.")
    if scope == BackupArchive.Scope.MAKERSPACE and makerspace is None:
        raise ValidationError("A makerspace archive requires a makerspace.")
    archive_id = uuid.uuid4()
    with transaction.atomic():
        superadmin_access_at_decision = None
        if scope == BackupArchive.Scope.MAKERSPACE:
            makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
            superadmin_access_at_decision = superadmin_access_decision(makerspace)
        retention_days = PlatformBackupSettings.load().retention_days
        archive = BackupArchive.objects.create(
            id=archive_id,
            scope=scope,
            makerspace=makerspace,
            superadmin_access_at_decision=superadmin_access_at_decision,
            requested_by=actor,
            object_key=f"backup-archives/{scope}/{archive_id}.tar.age",
            expires_at=timezone.now() + timedelta(days=retention_days),
        )
        audit.record(
            actor,
            "backup.archive_requested",
            makerspace=makerspace,
            target=archive,
            meta={"scope": scope, "archives_outside_purge_guarantee": True},
        )
    return archive


def run_archive(archive_id):
    try:
        with deployment_operation_lock():
            return _run_archive_locked(archive_id)
    except Exception as exc:
        logger.exception("backup_archive_failed", extra={"archive_id": str(archive_id)})
        archive = BackupArchive.objects.filter(pk=archive_id).first()
        if archive and archive.status in {
            BackupArchive.Status.PENDING, BackupArchive.Status.RUNNING,
        }:
            _fail_archive(archive, _safe_failure_detail(exc))
    return BackupArchive.objects.get(pk=archive_id)


def _run_archive_locked(archive_id):
    holder = uuid.uuid4()
    archive = None
    tempdir = None
    try:
        if not _claim_lease(holder):
            raise RuntimeError("Another backup already holds the deployment lease.")
        archive = _claim_archive(archive_id)
        if archive is None:
            return None
        build = build_archive(archive)
        encrypted, manifest, tempdir, archive_sha256 = build
        size = os.path.getsize(encrypted)
        if archive.scope == BackupArchive.Scope.DEPLOYMENT:
            upload_verify_and_promote(archive, build, size)
        else:
            storage.upload_archive(archive.object_key, encrypted)
            _complete_archive(archive.pk, manifest, size, archive_sha256)
        return BackupArchive.objects.get(pk=archive_id)
    except Exception as exc:
        if archive is not None:
            if isinstance(exc, (ArtifactLedgerMismatch, storage.BackupVerificationError)):
                mark_failed(archive.pk, "promotion_revalidation_failed")
            _fail_archive(archive, _safe_failure_detail(exc))
        raise
    finally:
        if tempdir is not None:
            tempdir.cleanup()
        _release_lease(holder)


@transaction.atomic
def _claim_archive(archive_id):
    # No select_related on the locked read: `makerspace` and `requested_by` are both
    # nullable, so select_related turns them into LEFT OUTER JOINs and Postgres refuses
    # outright -- "FOR UPDATE cannot be applied to the nullable side of an outer join".
    # They lazy-load in one extra query, free next to the writes this transaction
    # already performs. Same reason as procurement.move_to_printing.
    archive = BackupArchive.objects.select_for_update().filter(pk=archive_id).first()
    if archive is None or archive.status != BackupArchive.Status.PENDING:
        return None
    archive.status = BackupArchive.Status.RUNNING
    archive.started_at = timezone.now()
    archive.failure_detail = ""
    archive.save(update_fields=("status", "started_at", "failure_detail", "updated_at"))
    return archive


@transaction.atomic
def _complete_archive(archive_id, manifest, size, archive_sha256):
    archive = BackupArchive.objects.select_for_update().get(pk=archive_id)
    if archive.status != BackupArchive.Status.RUNNING:
        raise RuntimeError("The claimed backup changed state before completion.")
    archive.status = BackupArchive.Status.AVAILABLE
    archive.manifest = manifest
    archive.size_bytes = size
    archive.archive_sha256 = archive_sha256
    archive.age_encrypted = True
    archive.completed_at = timezone.now()
    archive.save(update_fields=(
        "status", "manifest", "size_bytes", "archive_sha256", "age_encrypted",
        "completed_at", "updated_at",
    ))
    settings_row = PlatformBackupSettings.load()
    settings_row.last_success_at = archive.completed_at
    settings_row.last_error = ""
    settings_row.save(update_fields=("last_success_at", "last_error", "updated_at"))
    audit.record(
        archive.requested_by,
        "backup.archive_completed",
        makerspace=archive.makerspace,
        target=archive,
        meta={"scope": archive.scope, "size_bytes": size},
    )


def _fail_archive(archive, detail):
    ledger = BackupArtifactLedger.objects.filter(pk=archive.pk).first()
    if ledger and ledger.state in {
        BackupArtifactLedger.State.AVAILABLE,
        BackupArtifactLedger.State.SUPERSEDED,
        BackupArtifactLedger.State.BYTES_DELETED,
        BackupArtifactLedger.State.FINAL_VERIFIED,
    }:
        return
    if ledger:
        mark_failed(ledger.artifact_id, "archive_run_failed")
        storage.delete_archive(ledger.staging_locator)
        storage.delete_archive(ledger.final_locator)
    else:
        storage.delete_archive(archive.object_key)
    message = str(detail).strip()[:500]
    updated = BackupArchive.objects.filter(
        pk=archive.pk,
        status__in=(BackupArchive.Status.PENDING, BackupArchive.Status.RUNNING),
    ).update(
        status=BackupArchive.Status.FAILED,
        failure_detail=message,
        completed_at=timezone.now(),
        download_token_digest="",
        download_token_expires_at=None,
    )
    if not updated:
        return
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


def fail_archive_dispatch(archive, exc):
    logger.exception(
        "backup_archive_dispatch_failed",
        exc_info=exc,
        extra={"archive_id": str(archive.pk)},
    )
    _fail_archive(archive, "The backup worker could not accept the job.")


def _safe_failure_detail(exc):
    if isinstance(exc, (BackupBuildError, storage.BackupStorageError, ArtifactLedgerMismatch, OperationLockUnavailable)):
        return str(exc)[:500]
    return "The backup failed unexpectedly; inspect server logs."


@transaction.atomic
def _claim_lease(holder):
    row, _ = BackupLease.objects.select_for_update().get_or_create(name="deployment-backup")
    now = timezone.now()
    if row.leased_until and row.leased_until > now:
        return False
    row.holder = holder
    row.leased_until = now + timedelta(seconds=settings.BACKUP_LEASE_SECONDS)
    row.save(update_fields=("holder", "leased_until", "updated_at"))
    return True


@transaction.atomic
def _release_lease(holder):
    BackupLease.objects.filter(name="deployment-backup", holder=holder).update(
        holder=None, leased_until=None
    )


def schedule_deployment_backup():
    with deployment_operation_lock():
        with transaction.atomic():
            row = PlatformBackupSettings.objects.select_for_update().filter(pk=1).first()
            if row is None:
                row = PlatformBackupSettings.objects.create(pk=1)
            now = timezone.now()
            if not row.automatic_backups_enabled:
                return None
            if row.last_scheduled_at and row.last_scheduled_at > now - timedelta(hours=20):
                return None
            row.last_scheduled_at = now
            row.save(update_fields=("last_scheduled_at", "updated_at"))
            archive = create_archive(None, scope=BackupArchive.Scope.DEPLOYMENT)
        return _run_archive_locked(archive.pk)
