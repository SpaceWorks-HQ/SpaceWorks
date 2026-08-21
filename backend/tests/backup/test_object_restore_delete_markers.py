from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.backup import object_restore
from apps.backup.models import BackupArchive, RestoreOperation, RestoreRollbackObject


pytestmark = pytest.mark.django_db


class VersionHistoryClient:
    def __init__(self, key, entries):
        self.key = key
        self.entries = list(entries)
        self.deleted = []

    def list_object_versions(self, **kwargs):
        assert kwargs["MaxKeys"] == 1
        previous = kwargs.get("VersionIdMarker")
        start = 0
        if previous is not None:
            start = next(
                index + 1
                for index, entry in enumerate(self.entries)
                if entry[0] == previous
            )
        if start >= len(self.entries):
            return {"IsTruncated": False}
        version_id, is_delete_marker = self.entries[start]
        field = "DeleteMarkers" if is_delete_marker else "Versions"
        truncated = start + 1 < len(self.entries)
        page = {
            field: [{"Key": self.key, "VersionId": version_id}],
            "IsTruncated": truncated,
        }
        if truncated:
            page.update(
                NextKeyMarker=self.key,
                NextVersionIdMarker=version_id,
            )
        return page

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)
        version_id = kwargs["VersionId"]
        self.entries = [entry for entry in self.entries if entry[0] != version_id]


def restore_fixture():
    actor = User.objects.create_superuser(
        username="delete-marker-restore", password="secret"
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key="backup-archives/deployment/delete-marker.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    return RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor,
    )


def test_absent_via_delete_marker_rollback_preserves_older_versions(
    monkeypatch, tmp_path
):
    restore = restore_fixture()
    key = "events/delete-marker/image.jpg"
    client = VersionHistoryClient(
        key,
        [("source-marker", True), ("older-two", False), ("older-one", False)],
    )
    monkeypatch.setattr(object_restore.storage, "client", lambda: client)
    monkeypatch.setattr(
        object_restore.storage,
        "ensure_versioning_or_quiescence",
        lambda _bucket: "versioned",
    )
    monkeypatch.setattr(object_restore, "_head", lambda *_args: None)
    monkeypatch.setattr(object_restore, "_journal", lambda *_args: None)

    row = object_restore._prepare_rollback(
        restore,
        {"key": key, "bucket_kind": RestoreRollbackObject.BucketKind.PRIVATE},
        tmp_path / "journal.jsonl",
    )
    assert row.source_absent_marker_version_id == "source-marker"

    client.entries.insert(0, ("attempted-replacement", False))
    object_restore.rollback_objects(restore)

    assert client.deleted == [{
        "Bucket": object_restore.settings.AWS_STORAGE_BUCKET_NAME,
        "Key": key,
        "VersionId": "attempted-replacement",
    }]
    assert client.entries == [
        ("source-marker", True),
        ("older-two", False),
        ("older-one", False),
    ]


def test_genuinely_absent_versioned_key_keeps_delete_all_versions_rollback(
    monkeypatch, tmp_path
):
    restore = restore_fixture()
    key = "events/new/image.jpg"
    client = VersionHistoryClient(key, [])
    monkeypatch.setattr(object_restore.storage, "client", lambda: client)
    monkeypatch.setattr(
        object_restore.storage,
        "ensure_versioning_or_quiescence",
        lambda _bucket: "versioned",
    )
    monkeypatch.setattr(object_restore, "_head", lambda *_args: None)
    monkeypatch.setattr(object_restore, "_journal", lambda *_args: None)
    row = object_restore._prepare_rollback(
        restore,
        {"key": key, "bucket_kind": RestoreRollbackObject.BucketKind.PRIVATE},
        tmp_path / "journal.jsonl",
    )
    deleted = []
    monkeypatch.setattr(
        object_restore,
        "delete_all_versions",
        lambda _client, **kwargs: deleted.append(kwargs),
    )

    object_restore.rollback_objects(restore)

    assert row.source_absent_marker_version_id == ""
    assert deleted == [{
        "bucket": object_restore.settings.AWS_STORAGE_BUCKET_NAME,
        "key": key,
    }]


def test_missing_recorded_delete_marker_fails_closed_without_deleting(monkeypatch):
    restore = restore_fixture()
    key = "events/missing-marker/image.jpg"
    row = RestoreRollbackObject.objects.create(
        restore=restore,
        bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
        source_key=key,
        source_was_absent=True,
        source_absent_marker_version_id="missing-marker",
        expires_at=timezone.now() + timedelta(days=7),
    )
    client = VersionHistoryClient(
        key,
        [("attempted-replacement", False), ("older-two", False), ("older-one", False)],
    )
    monkeypatch.setattr(object_restore.storage, "client", lambda: client)

    with pytest.raises(object_restore.ObjectRestoreError, match="was not found"):
        object_restore.rollback_objects(restore)

    assert row.source_absent_marker_version_id == "missing-marker"
    assert client.deleted == []
