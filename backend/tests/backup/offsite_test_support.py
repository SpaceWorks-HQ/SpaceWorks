"""Shared fixtures for the offsite destination tests: real MinIO, real bytes."""

import hashlib
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.backup import storage
from apps.backup.models import BackupArchive, BackupDestination, BackupRun


def destination_bucket():
    name = f"offsite-{uuid.uuid4().hex[:12]}"
    storage.client().create_bucket(Bucket=name)
    return name


def make_destination(bucket, *, name=None, endpoint=None, retention_days=90):
    destination = BackupDestination(
        name=name or f"dest-{uuid.uuid4().hex[:8]}",
        endpoint_url=endpoint or settings.AWS_S3_ENDPOINT_URL,
        bucket=bucket,
        region=settings.AWS_S3_REGION_NAME or "us-east-1",
        prefix="lane-tests",
        addressing_style="path",
        retention_days=retention_days,
    )
    destination.set_access_key_id(settings.AWS_ACCESS_KEY_ID)
    destination.set_secret_access_key(settings.AWS_SECRET_ACCESS_KEY)
    destination.save()
    return destination


def stored_archive(*, scope=BackupArchive.Scope.DEPLOYMENT, makerspace=None, run=None,
                   payload=None, completed_at=None, expires_at=None):
    """An AVAILABLE archive whose ciphertext really sits in the primary bucket."""
    payload = payload if payload is not None else uuid.uuid4().bytes * 4096
    archive_id = uuid.uuid4()
    key = f"backup-archives/{scope}/{archive_id}.tar.age"
    storage.client().put_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key, Body=payload)
    completed = completed_at or timezone.now()
    return BackupArchive.objects.create(
        id=archive_id,
        scope=scope,
        makerspace=makerspace,
        backup_run=run,
        superadmin_access_at_decision=False if scope == BackupArchive.Scope.MAKERSPACE else None,
        status=BackupArchive.Status.AVAILABLE,
        object_key=key,
        manifest={"format": "test-format"},
        size_bytes=len(payload),
        archive_sha256=hashlib.sha256(payload).hexdigest(),
        age_encrypted=True,
        completed_at=completed,
        expires_at=expires_at or completed + timedelta(days=30),
    )


def open_run(makerspace_ids=()):
    return BackupRun.objects.create(
        cohort_at=timezone.now(),
        flag_snapshot={str(pk): False for pk in makerspace_ids},
        holder=uuid.uuid4(),
    )


def remote_bytes(destination, locator):
    return storage.client().get_object(Bucket=destination.bucket, Key=locator)["Body"].read()


@pytest.fixture
def offsite_bucket():
    return destination_bucket()
