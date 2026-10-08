"""Offsite destinations against a real S3-compatible store (the harness MinIO)."""

import hashlib
import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.backup import offsite_client, storage
from apps.backup.models import (
    BackupArchive,
    BackupDestination,
    BackupDestinationUpload,
    BackupRun,
)
from apps.backup.offsite_push import (
    BACKOFF_CAP_SECONDS,
    backoff_seconds,
    enqueue_offsite_uploads,
    push_due_uploads,
)
from apps.backup.offsite_retention import prune_offsite_copies
from apps.backup.offsite_restore import rehydrate_archive, validate_rehydration
from apps.makerspaces.models import Makerspace
from tests.backup.offsite_test_support import (
    make_destination,
    offsite_bucket,  # noqa: F401  (fixture)
    open_run,
    remote_bytes,
    stored_archive,
)

pytestmark = pytest.mark.django_db


def superadmin():
    return User.objects.create_superuser(username="offsite-super", password="x")


def client_for(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def test_destination_api_stores_credentials_encrypted_and_never_returns_them(offsite_bucket):
    actor = superadmin()
    response = client_for(actor).post(
        reverse("admin-backup-destinations"),
        {
            "name": "cold-r2", "endpoint_url": "https://example.r2.test", "bucket": offsite_bucket,
            "access_key_id": "AKIA-RAW-ID", "secret_access_key": "raw-secret-value",
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    body = json.dumps(response.data)
    assert "raw-secret-value" not in body and "AKIA-RAW-ID" not in body
    assert response.data["credentials_set"] is True
    row = BackupDestination.objects.get(name="cold-r2")
    assert row.secret_access_key.startswith("fernet:")
    assert "raw-secret-value" not in row.secret_access_key
    assert row.get_secret_access_key() == "raw-secret-value"
    audit = AuditLog.objects.get(action="backup.destination_created")
    assert "raw-secret-value" not in json.dumps(audit.meta)
    assert audit.meta["credentials_changed"] == ["access_key_id", "secret_access_key"]


def test_destination_api_is_superadmin_only_and_requires_credentials(offsite_bucket):
    ordinary = User.objects.create_user(username="offsite-ordinary", access_status=User.AccessStatus.ACTIVE)
    url = reverse("admin-backup-destinations")
    assert client_for(ordinary).get(url).status_code == 403
    response = client_for(superadmin()).post(url, {"name": "x", "bucket": offsite_bucket}, format="json")
    assert response.status_code == 400


def test_push_fans_out_eligible_archives_and_verifies_by_read_back(offsite_bucket):
    space = Makerspace.objects.create(name="Sovereign", slug="offsite-sovereign")
    run = open_run([space.pk])
    deployment = stored_archive()
    tenant_run = stored_archive(scope=BackupArchive.Scope.MAKERSPACE, makerspace=space, run=run)
    stored_archive(scope=BackupArchive.Scope.MAKERSPACE, makerspace=space)  # ad hoc: not pushed
    stored_archive(expires_at=timezone.now() - timedelta(seconds=1))
    destination = make_destination(offsite_bucket)

    assert enqueue_offsite_uploads() == 2
    assert enqueue_offsite_uploads() == 0
    assert push_due_uploads() == 2

    for archive in (deployment, tenant_run):
        row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
        assert row.state == BackupDestinationUpload.State.BYTES_VERIFIED
        assert row.verified_sha256 == archive.archive_sha256
        assert row.integrity_source == BackupDestinationUpload.IntegritySource.ARCHIVE_ROW
        assert hashlib.sha256(remote_bytes(destination, row.remote_locator)).hexdigest() == archive.archive_sha256
        index = json.loads(remote_bytes(destination, offsite_client.index_locator(row.remote_locator)))
        assert index["sha256"] == archive.archive_sha256 and index["archive_id"] == str(archive.pk)
    destination.refresh_from_db()
    assert destination.last_success_at is not None
    assert AuditLog.objects.filter(action="backup.offsite_copy_verified").count() == 2


def test_destination_outage_backs_off_and_never_touches_backup_state(offsite_bucket):
    archive = stored_archive()
    run = open_run()
    make_destination(offsite_bucket, endpoint="http://127.0.0.1:1")
    enqueue_offsite_uploads()

    push_due_uploads()

    row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
    assert row.state == BackupDestinationUpload.State.PENDING
    assert row.attempts == 1 and row.last_error_code
    assert row.next_attempt_at > timezone.now() + timedelta(seconds=250)
    assert push_due_uploads() == 0  # not due again yet
    archive.refresh_from_db()
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert BackupRun.objects.get(pk=run.pk).status == BackupRun.Status.PENDING
    assert backoff_seconds(1) == 300 and backoff_seconds(50) == BACKOFF_CAP_SECONDS


def test_corrupted_primary_bytes_are_refused_not_copied_as_verified(offsite_bucket):
    archive = stored_archive()
    storage.client().put_object(
        Bucket=storage.settings.AWS_STORAGE_BUCKET_NAME, Key=archive.object_key, Body=b"tampered"
    )
    make_destination(offsite_bucket)
    enqueue_offsite_uploads()

    push_due_uploads()

    row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
    assert row.state == BackupDestinationUpload.State.PENDING
    assert row.last_error_code == "source_digest_mismatch"


def test_archive_gone_before_upload_is_abandoned(offsite_bucket):
    archive = stored_archive()
    make_destination(offsite_bucket)
    enqueue_offsite_uploads()
    BackupArchive.objects.filter(pk=archive.pk).update(status=BackupArchive.Status.EXPIRED)

    push_due_uploads()

    row = BackupDestinationUpload.objects.get(archive_id_snapshot=archive.pk)
    assert row.state == BackupDestinationUpload.State.ABANDONED


def test_retention_prunes_expired_copies_but_keeps_the_newest(offsite_bucket):
    old = stored_archive(completed_at=timezone.now() - timedelta(days=10))
    new = stored_archive(completed_at=timezone.now() - timedelta(days=5))
    destination = make_destination(offsite_bucket, retention_days=1)
    enqueue_offsite_uploads()
    push_due_uploads()
    old_row = BackupDestinationUpload.objects.get(archive_id_snapshot=old.pk)
    new_row = BackupDestinationUpload.objects.get(archive_id_snapshot=new.pk)

    assert prune_offsite_copies() == 1

    old_row.refresh_from_db()
    new_row.refresh_from_db()
    assert old_row.state == BackupDestinationUpload.State.DELETED
    assert new_row.state == BackupDestinationUpload.State.BYTES_VERIFIED
    with pytest.raises(Exception):
        remote_bytes(destination, old_row.remote_locator)
    assert remote_bytes(destination, new_row.remote_locator)
    assert AuditLog.objects.filter(action="backup.offsite_copy_pruned").count() == 1


def test_rehydrate_restores_lost_primary_bytes_through_create_only_promotion(offsite_bucket):
    archive = stored_archive()
    destination = make_destination(offsite_bucket)
    enqueue_offsite_uploads()
    push_due_uploads()

    with pytest.raises(Exception, match="primary copy is present"):
        validate_rehydration(archive, destination)
    storage.delete_archive(archive.object_key)
    assert storage.object_exists(archive.object_key) is False

    ok = rehydrate_archive(archive.pk, destination.pk, actor=None)
    assert ok is True, list(AuditLog.objects.filter(action='backup.archive_rehydrate_failed').values_list('meta', flat=True))

    restored = storage.client().get_object(
        Bucket=storage.settings.AWS_STORAGE_BUCKET_NAME, Key=archive.object_key
    )["Body"].read()
    assert hashlib.sha256(restored).hexdigest() == archive.archive_sha256
    assert AuditLog.objects.filter(action="backup.archive_rehydrated").exists()


def test_rehydrate_api_refuses_without_a_verified_copy(offsite_bucket):
    archive = stored_archive()
    destination = make_destination(offsite_bucket)
    response = client_for(superadmin()).post(
        reverse("admin-backup-archive-rehydrate", kwargs={"archive_id": archive.pk}),
        {"destination": destination.pk}, format="json",
    )
    assert response.status_code == 400


def test_retire_wipes_credentials_and_stops_pushing(offsite_bucket):
    destination = make_destination(offsite_bucket)
    response = client_for(superadmin()).post(
        reverse("admin-backup-destination-retire", kwargs={"destination_id": destination.pk})
    )
    assert response.status_code == 200
    destination.refresh_from_db()
    assert destination.retired_at and not destination.access_key_id and not destination.secret_access_key
    stored_archive()
    assert enqueue_offsite_uploads() == 0


def test_probe_reports_success_and_failure_codes(offsite_bucket):
    actor = superadmin()
    good = make_destination(offsite_bucket)
    bad = make_destination(offsite_bucket, endpoint="http://127.0.0.1:1")
    ok = client_for(actor).post(reverse("admin-backup-destination-probe", kwargs={"destination_id": good.pk}))
    failed = client_for(actor).post(reverse("admin-backup-destination-probe", kwargs={"destination_id": bad.pk}))
    assert ok.data == {"ok": True, "error_code": ""}
    assert failed.data["ok"] is False and failed.data["error_code"]


def test_scheduled_task_dispatches_push_and_survives_its_failure(monkeypatch):
    from apps.backup import tasks

    run = open_run()
    monkeypatch.setattr(tasks, "schedule_deployment_backup", lambda: run)

    def broken():
        raise RuntimeError("broker down")

    monkeypatch.setattr(tasks.push_offsite_backups_task, "delay", broken)
    assert tasks.scheduled_deployment_backup_task.apply().get() is False
