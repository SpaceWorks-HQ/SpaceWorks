"""Retention: `purge_expired_archives` and `cleanup_expired_rollback_objects` (audit gaps 19, 8)."""

import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import storage
from apps.backup.models import BackupArchive, RestoreOperation, RestoreRollbackObject
from apps.backup.object_restore import cleanup_expired_rollback_objects
from apps.backup.services import purge_expired_archives
from tests.backup.offsite_test_support import stored_archive

pytestmark = pytest.mark.django_db


def _restore_for(archive):
    actor = User.objects.create_user(username=f"r-{uuid.uuid4().hex[:6]}")
    return RestoreOperation.objects.create(
        archive=archive, kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor, requested_by_username_snapshot=actor.username,
        stage=RestoreOperation.Stage.FAILED,
    )


def _past(days):
    return timezone.now() - timedelta(days=days)


def test_expired_rows_kept_for_restore_history_never_starve_newer_ones():
    kept = [stored_archive(completed_at=_past(40), expires_at=_past(10 - i)) for i in range(2)]
    for archive in kept:
        _restore_for(archive)
    plain = stored_archive(completed_at=_past(40), expires_at=_past(1))
    fresh = stored_archive()

    assert purge_expired_archives(limit=2) == 2
    assert purge_expired_archives(limit=2) == 1  # the old query re-selected the EXPIRED rows

    for archive in kept:
        archive.refresh_from_db()
        assert archive.status == BackupArchive.Status.EXPIRED and archive.size_bytes == 0
        assert storage.object_exists(archive.object_key) is False
    assert not BackupArchive.objects.filter(pk=plain.pk).exists()
    assert storage.object_exists(plain.object_key) is False
    fresh.refresh_from_db()
    assert fresh.status == BackupArchive.Status.AVAILABLE
    assert storage.object_exists(fresh.object_key) is True
    assert AuditLog.objects.filter(action="backup.archive_pruned").count() == 3
    assert purge_expired_archives() == 0


def test_purge_removes_the_archive_staging_prefix_too():
    archive = stored_archive(completed_at=_past(40), expires_at=_past(1))
    staging = f"backup-archives/staging/{archive.pk}/{uuid.uuid4()}.tar.age"
    storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=staging, Body=b"x")

    purge_expired_archives()

    assert storage.object_exists(staging) is False


def test_purge_removes_compound_staging_file_and_recorded_attempt_key():
    archive = stored_archive(completed_at=_past(40), expires_at=_past(1))
    compound_key = storage.staging_locator(archive.pk)
    attempt_key = f"backup-archives/staging/{archive.pk}/attempt.tar.age"
    BackupArchive.objects.filter(pk=archive.pk).update(staging_object_key=attempt_key)
    for key in (compound_key, attempt_key):
        storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key, Body=b"x")

    assert purge_expired_archives() == 1

    assert not storage.object_exists(compound_key)
    assert not storage.object_exists(attempt_key)


def test_staging_cleanup_failure_keeps_the_archive_retryable(monkeypatch):
    archive = stored_archive(completed_at=_past(40), expires_at=_past(1))
    real_delete = storage.delete_archive_prefix
    monkeypatch.setattr(storage, "delete_archive_prefix", lambda prefix: False)
    assert purge_expired_archives() == 0
    archive.refresh_from_db()
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert not AuditLog.objects.filter(action="backup.archive_pruned").exists()

    monkeypatch.setattr(storage, "delete_archive_prefix", real_delete)
    assert purge_expired_archives() == 1
    assert not BackupArchive.objects.filter(pk=archive.pk).exists()


def test_retention_never_prunes_an_in_flight_archive(monkeypatch):
    archives = [BackupArchive.objects.create(
        scope="deployment", status=status, object_key=f"backup/{uuid.uuid4()}", expires_at=_past(1),
    ) for status in ("pending", "running", "promoting")]
    deleted_keys = []
    monkeypatch.setattr(storage, "delete_archive", lambda key: deleted_keys.append(key) or True)
    assert purge_expired_archives() == 0
    assert deleted_keys == []
    assert BackupArchive.objects.filter(pk__in=[archive.pk for archive in archives]).count() == 3


def test_expired_rollback_copies_are_deleted_and_live_ones_kept():
    archive = stored_archive()
    restore = _restore_for(archive)
    copy_key = f"restore-rollback/{uuid.uuid4()}"
    live_key = f"restore-rollback/{uuid.uuid4()}"
    for key in (copy_key, live_key):
        storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key, Body=b"copy")
    common = dict(restore=restore, bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE)
    expired = RestoreRollbackObject.objects.create(
        copy_key=copy_key, expires_at=_past(1), source_key=f"evidence/{uuid.uuid4()}", **common
    )
    live = RestoreRollbackObject.objects.create(
        copy_key=live_key, expires_at=timezone.now() + timedelta(days=1),
        source_key=f"evidence/{uuid.uuid4()}", **common
    )

    assert cleanup_expired_rollback_objects() == 1

    assert not RestoreRollbackObject.objects.filter(pk=expired.pk).exists()
    assert RestoreRollbackObject.objects.filter(pk=live.pk).exists()
    assert storage.object_exists(copy_key) is False
    assert storage.object_exists(live_key) is True


def test_rollback_cleanup_storage_failure_keeps_the_journal_for_retry(monkeypatch):
    from apps.backup import object_restore

    restore = _restore_for(stored_archive())
    row = RestoreRollbackObject.objects.create(
        restore=restore, bucket_kind="private", copy_key=f"rollback/{uuid.uuid4()}",
        source_key=f"evidence/{uuid.uuid4()}", expires_at=_past(1),
    )

    def unavailable(*args, **kwargs):
        raise OSError("store unavailable")

    monkeypatch.setattr(object_restore, "delete_all_versions", unavailable)
    assert cleanup_expired_rollback_objects() == 0
    assert RestoreRollbackObject.objects.filter(pk=row.pk).exists()


@pytest.mark.parametrize("stage,should_delete_version", [("completed", True), ("failed", False)])
def test_rollback_cleanup_only_removes_the_exact_retained_source_version_after_success(monkeypatch, stage, should_delete_version):
    from types import SimpleNamespace

    restore = _restore_for(stored_archive())
    RestoreOperation.objects.filter(pk=restore.pk).update(stage=stage)
    row = RestoreRollbackObject.objects.create(
        restore=restore, bucket_kind="private", copy_key="", source_key="evidence/original",
        source_version_id="retained-original-version", expires_at=_past(1),
    )
    deleted = []
    monkeypatch.setattr(storage, "client", lambda: SimpleNamespace(
        delete_object=lambda **kwargs: deleted.append(kwargs),
    ))

    assert cleanup_expired_rollback_objects() == 1
    assert not RestoreRollbackObject.objects.filter(pk=row.pk).exists()
    assert deleted == ([{
        "Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": "evidence/original",
        "VersionId": "retained-original-version",
    }] if should_delete_version else [])
