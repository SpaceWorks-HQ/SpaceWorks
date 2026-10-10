"""Lost-primary recovery follows staging verification and never overwrites final bytes."""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.backup import storage
from apps.backup.models import BackupDestinationUpload
from apps.backup.offsite_push import enqueue_offsite_uploads, push_due_uploads
from apps.backup.offsite_restore import rehydrate_archive, validate_rehydration
from rest_framework.exceptions import ValidationError
from tests.backup.offsite_test_support import (
    make_destination, offsite_bucket, stored_archive,  # noqa: F401
)

pytestmark = pytest.mark.django_db


def _lost_primary(bucket):
    archive = stored_archive()
    destination = make_destination(bucket)
    enqueue_offsite_uploads()
    push_due_uploads()
    assert storage.delete_archive(archive.object_key)
    return archive, destination


def test_rehydration_verifies_staging_then_final_and_removes_the_attempt_key(offsite_bucket, monkeypatch):
    archive, destination = _lost_primary(offsite_bucket)
    real_verify = storage.stream_verify
    keys = []

    def verify(key, **kwargs):
        keys.append(key)
        return real_verify(key, **kwargs)

    monkeypatch.setattr(storage, "stream_verify", verify)

    assert rehydrate_archive(archive.pk, destination.pk)

    assert len(keys) == 2
    assert keys[0].startswith(f"backup-archives/staging/{archive.pk}/rehydrate-")
    assert keys[1] == archive.object_key
    assert not storage.object_exists(keys[0])
    archive.refresh_from_db()
    assert archive.status == archive.Status.AVAILABLE


def test_a_primary_copy_reappearing_after_admission_is_never_overwritten(offsite_bucket, monkeypatch):
    archive, destination = _lost_primary(offsite_bucket)
    real_promote = storage.create_final_from_staging
    attempted_keys = []

    def race(staging, final):
        attempted_keys.append(staging)
        storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=final,
                                    Body=b"concurrently restored bytes")
        return real_promote(staging, final)

    monkeypatch.setattr(storage, "create_final_from_staging", race)

    assert rehydrate_archive(archive.pk, destination.pk) is False

    body = storage.client().get_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                                      Key=archive.object_key)["Body"]
    try:
        assert body.read() == b"concurrently restored bytes"
    finally:
        body.close()
    assert not storage.object_exists(attempted_keys[0])
    assert AuditLog.objects.filter(action="backup.archive_rehydrate_failed").exists()
    assert not AuditLog.objects.filter(action="backup.archive_rehydrated").exists()


def test_corrupt_offsite_copy_cannot_reach_primary_staging(offsite_bucket, monkeypatch):
    archive, destination = _lost_primary(offsite_bucket)
    row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
    storage.client().put_object(Bucket=destination.bucket, Key=row.remote_locator, Body=b"corrupt")
    writes = []
    monkeypatch.setattr(storage, "upload_staging", lambda *args: writes.append(args))
    assert rehydrate_archive(archive.pk, destination.pk) is False
    assert writes == []
    assert not storage.object_exists(archive.object_key)


def test_expired_archive_is_refused_even_when_an_offsite_copy_survives(offsite_bucket):
    archive, destination = _lost_primary(offsite_bucket)
    archive.expires_at = timezone.now() - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="unexpired"):
        validate_rehydration(archive, destination)
