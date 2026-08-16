import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.archive_builder import BackupBuildError, build_archive
from apps.backup.archive_import import import_disaster_archive
from apps.backup.models import (
    BackupArchive,
    BackupLease,
    PlatformBackupSettings,
)
from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock


logger = logging.getLogger(__name__)


class DownloadTokenError(RuntimeError):
    pass


def create_archive(actor, *, scope, makerspace=None):
    if scope == BackupArchive.Scope.DEPLOYMENT and makerspace is not None:
        raise ValidationError("A deployment archive cannot be scoped to a makerspace.")
    if scope == BackupArchive.Scope.MAKERSPACE and makerspace is None:
        raise ValidationError("A makerspace archive requires a makerspace.")
    archive_id = uuid.uuid4()
    with transaction.atomic():
        retention_days = PlatformBackupSettings.load().retention_days
        archive = BackupArchive.objects.create(
            id=archive_id,
            scope=scope,
            makerspace=makerspace,
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
        encrypted, manifest, tempdir = build_archive(archive)
        size = os.path.getsize(encrypted)
        storage.upload_archive(archive.object_key, encrypted)
        _complete_archive(archive.pk, manifest, size)
        return BackupArchive.objects.get(pk=archive_id)
    except Exception as exc:
        if archive is not None:
            _fail_archive(archive, _safe_failure_detail(exc))
        raise
    finally:
        if tempdir is not None:
            tempdir.cleanup()
        _release_lease(holder)


@transaction.atomic
def _claim_archive(archive_id):
    archive = BackupArchive.objects.select_for_update().select_related(
        "makerspace", "requested_by"
    ).filter(pk=archive_id).first()
    if archive is None or archive.status != BackupArchive.Status.PENDING:
        return None
    archive.status = BackupArchive.Status.RUNNING
    archive.started_at = timezone.now()
    archive.failure_detail = ""
    archive.save(update_fields=("status", "started_at", "failure_detail", "updated_at"))
    return archive


@transaction.atomic
def _complete_archive(archive_id, manifest, size):
    archive = BackupArchive.objects.select_for_update().select_related(
        "makerspace", "requested_by"
    ).get(pk=archive_id)
    if archive.status != BackupArchive.Status.RUNNING:
        raise RuntimeError("The claimed backup changed state before completion.")
    archive.status = BackupArchive.Status.AVAILABLE
    archive.manifest = manifest
    archive.size_bytes = size
    archive.age_encrypted = True
    archive.completed_at = timezone.now()
    archive.save()
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
    storage.delete_archive(archive.object_key)
    message = str(detail).strip()[:500]
    BackupArchive.objects.filter(pk=archive.pk).update(
        status=BackupArchive.Status.FAILED,
        failure_detail=message,
        completed_at=timezone.now(),
        download_token_digest="",
        download_token_expires_at=None,
    )
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
    if isinstance(exc, (BackupBuildError, storage.BackupStorageError, OperationLockUnavailable)):
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


@transaction.atomic
def issue_download_token(archive, actor):
    locked = BackupArchive.objects.select_for_update().get(pk=archive.pk)
    if locked.status != BackupArchive.Status.AVAILABLE or locked.expires_at <= timezone.now():
        raise ValidationError("This backup archive is not available for download.")
    raw = secrets.token_urlsafe(32)
    locked.download_token_digest = hashlib.sha256(raw.encode()).hexdigest()
    locked.download_token_expires_at = timezone.now() + timedelta(
        seconds=settings.BACKUP_DOWNLOAD_TTL_SECONDS
    )
    locked.download_token_consumed_at = None
    locked.save(update_fields=(
        "download_token_digest", "download_token_expires_at",
        "download_token_consumed_at", "updated_at",
    ))
    audit.record(
        actor, "backup.download_url_issued", makerspace=locked.makerspace,
        target=locked, meta={"archives_outside_purge_guarantee": True},
    )
    return raw, locked.download_token_expires_at


@transaction.atomic
def consume_download_token(archive_id, raw):
    archive = BackupArchive.objects.select_for_update().select_related("makerspace").filter(pk=archive_id).first()
    now = timezone.now()
    expected = hashlib.sha256(raw.encode()).hexdigest()
    valid = bool(
        archive and archive.status == BackupArchive.Status.AVAILABLE
        and archive.download_token_digest and archive.download_token_consumed_at is None
        and archive.download_token_expires_at and archive.download_token_expires_at > now
        and hmac.compare_digest(archive.download_token_digest, expected)
    )
    if not valid:
        raise DownloadTokenError("The backup download is invalid, expired, or already used.")
    archive.download_token_consumed_at = now
    archive.save(update_fields=("download_token_consumed_at", "updated_at"))
    audit.record(None, "backup.downloaded", makerspace=archive.makerspace, target=archive)
    return archive


def purge_expired_archives(limit=100):
    archives = list(BackupArchive.objects.filter(expires_at__lte=timezone.now()).order_by("pk")[:limit])
    deleted = 0
    for archive in archives:
        if storage.delete_archive(archive.object_key):
            if archive.restores.exists():
                archive.status = BackupArchive.Status.EXPIRED
                archive.size_bytes = 0
                archive.download_token_digest = ""
                archive.download_token_expires_at = None
                archive.save(update_fields=(
                    "status", "size_bytes", "download_token_digest",
                    "download_token_expires_at", "updated_at",
                ))
            else:
                archive.delete()
            deleted += 1
    return deleted
