"""Archive request, build, promotion, and failure lifecycles."""

import logging
import os
from datetime import timedelta
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.artifact_protocol import upload_verify_and_promote
from apps.backup.archive_builder import build_archive
from apps.backup.models import (
    BackupArchive,
    BackupRun,
    PlatformBackupSettings,
)
from apps.backup.operation_lock import deployment_operation_lock
from apps.backup.runs import BackupRunHolderMismatchError
from apps.backup.services_archive_failures import (
    _fail_archive,
    _safe_failure_detail,
    fail_archive_dispatch,
    sweep_stale_promotions,
)
from apps.backup.services_lease import _claim_lease, _release_lease
from apps.makerspaces.models import Makerspace


logger = logging.getLogger(__name__)


def superadmin_access_decision(makerspace):
    """Return the access decision from a makerspace row locked by the caller."""
    return makerspace.superadmin_access_enabled


def create_archive(
    actor,
    *,
    scope,
    makerspace=None,
    backup_run=None,
    superadmin_access_at_decision=None,
):
    if scope == BackupArchive.Scope.DEPLOYMENT and makerspace is not None:
        raise ValidationError("A deployment archive cannot be scoped to a makerspace.")
    if scope == BackupArchive.Scope.MAKERSPACE and makerspace is None:
        raise ValidationError("A makerspace archive requires a makerspace.")
    with transaction.atomic():
        locked_run = _lock_archive_run(backup_run)
        if makerspace is not None:
            makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
            if locked_run is None:
                superadmin_access_at_decision = superadmin_access_decision(makerspace)
            else:
                frozen = locked_run.flag_snapshot.get(str(makerspace.pk))
                if type(frozen) is not bool:
                    raise ValidationError(
                        "The makerspace is not in the backup run cohort."
                    )
                superadmin_access_at_decision = frozen
        archive_id = uuid.uuid4()
        archive = BackupArchive.objects.create(
            id=archive_id,
            scope=scope,
            makerspace=makerspace,
            requested_by=actor,
            backup_run=locked_run,
            superadmin_access_at_decision=superadmin_access_at_decision,
            object_key=f"backup-archives/{scope}/{archive_id}.tar.age",
        )
        audit.record(
            actor,
            "backup.archive_requested",
            makerspace=makerspace,
            target=archive,
            meta={"scope": scope, "archives_outside_purge_guarantee": True},
        )
    return archive


def _lock_archive_run(run):
    if run is None:
        return None
    locked = BackupRun.objects.select_for_update().get(pk=run.pk)
    if run.holder is None or locked.holder != run.holder:
        raise BackupRunHolderMismatchError(
            "Backup archive creation refused because the run holder does not match."
        )
    if locked.status not in (BackupRun.Status.PENDING, BackupRun.Status.RUNNING):
        raise ValidationError("A terminal backup run cannot create another archive.")
    return locked


def run_archive(archive_id):
    try:
        with deployment_operation_lock():
            sweep_stale_promotions()
            return _run_archive_locked(archive_id)
    except Exception:
        # A duplicate that loses the host lock owns no archive claim and therefore
        # must not fail the process that does own it.
        logger.exception("backup_archive_failed", extra={"archive_id": str(archive_id)})
        return BackupArchive.objects.filter(pk=archive_id).first()


def _run_archive_locked(archive_id, *, manage_lease=True, lease_holder=None):
    build_holder = uuid.uuid4()
    lease_holder = lease_holder or uuid.uuid4()
    archive = None
    expected_status = BackupArchive.Status.RUNNING
    tempdir = None
    lease_claimed = False
    try:
        if manage_lease:
            lease_claimed = _claim_lease(lease_holder)
            if not lease_claimed:
                raise RuntimeError("Another backup already holds the deployment lease.")
        archive = _claim_archive(archive_id, build_holder)
        if archive is None:
            return BackupArchive.objects.filter(pk=archive_id).first()
        build = build_archive(archive)
        encrypted, manifest, tempdir, archive_sha256 = build
        size = os.path.getsize(encrypted)
        if archive.scope == BackupArchive.Scope.DEPLOYMENT:
            if not _claim_promotion(archive.pk, build_holder):
                return BackupArchive.objects.get(pk=archive_id)
            expected_status = BackupArchive.Status.PROMOTING
            upload_verify_and_promote(archive, build, size)
        else:
            storage.upload_staging(archive.staging_object_key, encrypted)
            storage.stream_verify(
                archive.staging_object_key,
                expected_size=size,
                expected_sha256=archive_sha256,
            )
            if not _claim_promotion(archive.pk, build_holder):
                return BackupArchive.objects.get(pk=archive_id)
            expected_status = BackupArchive.Status.PROMOTING
            storage.create_final_from_staging(
                archive.staging_object_key, archive.object_key
            )
            storage.stream_verify(
                archive.object_key,
                expected_size=size,
                expected_sha256=archive_sha256,
            )
            _complete_archive(
                archive.pk, build_holder, manifest, size, archive_sha256
            )
        return BackupArchive.objects.get(pk=archive_id)
    except Exception as exc:
        if archive is not None:
            _fail_archive(
                archive.pk,
                build_holder,
                _safe_failure_detail(exc),
                expected_status=expected_status,
            )
        logger.exception(
            "backup_archive_build_failed", extra={"archive_id": str(archive_id)}
        )
        return BackupArchive.objects.filter(pk=archive_id).first()
    finally:
        if tempdir is not None:
            tempdir.cleanup()
        if manage_lease and lease_claimed:
            _release_lease(lease_holder)


@transaction.atomic
def _claim_archive(archive_id, holder):
    staging_key = f"backup-archives/staging/{archive_id}/{holder}.tar.age"
    claimed = BackupArchive.objects.filter(
        pk=archive_id,
        status=BackupArchive.Status.PENDING,
        build_holder__isnull=True,
    ).update(
        status=BackupArchive.Status.RUNNING,
        build_holder=holder,
        staging_object_key=staging_key,
        started_at=timezone.now(),
        failure_detail="",
        updated_at=timezone.now(),
    )
    if not claimed:
        logger.info("backup_archive_claim_lost", extra={"archive_id": str(archive_id)})
        return None
    return BackupArchive.objects.get(pk=archive_id)


@transaction.atomic
def _claim_promotion(archive_id, holder):
    claimed = BackupArchive.objects.filter(
        pk=archive_id,
        status=BackupArchive.Status.RUNNING,
        build_holder=holder,
    ).update(status=BackupArchive.Status.PROMOTING, updated_at=timezone.now())
    if not claimed:
        logger.warning(
            "backup_archive_promotion_claim_lost",
            extra={"archive_id": str(archive_id)},
        )
    return bool(claimed)


def _complete_archive(archive_id, holder, manifest, size, archive_sha256):
    won = _commit_archive_available(
        archive_id, holder, manifest, size, archive_sha256
    )
    if won:
        storage.delete_archive_prefix(_staging_prefix(archive_id))
    return won


@transaction.atomic
def _commit_archive_available(archive_id, holder, manifest, size, archive_sha256):
    archive = BackupArchive.objects.select_for_update().filter(
        pk=archive_id,
        status=BackupArchive.Status.PROMOTING,
        build_holder=holder,
    ).first()
    if archive is None:
        logger.warning(
            "backup_archive_completion_fence_lost",
            extra={"archive_id": str(archive_id)},
        )
        return False
    completed_at = timezone.now()
    archive.status = BackupArchive.Status.AVAILABLE
    archive.manifest = manifest
    archive.size_bytes = size
    archive.archive_sha256 = archive_sha256
    archive.age_encrypted = True
    archive.completed_at = completed_at
    if archive.expires_at is None:
        archive.expires_at = completed_at + timedelta(
            days=PlatformBackupSettings.load().retention_days
        )
    archive.save()
    if archive.backup_run_id is None:
        PlatformBackupSettings.objects.update_or_create(
            pk=1, defaults={"last_success_at": completed_at, "last_error": ""}
        )
    audit.record(
        archive.requested_by,
        "backup.archive_completed",
        makerspace=archive.makerspace,
        target=archive,
        meta={"scope": archive.scope, "size_bytes": size},
    )
    return True


def _staging_prefix(archive_id):
    return f"backup-archives/staging/{archive_id}/"
