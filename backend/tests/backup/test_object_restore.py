from datetime import timedelta
import json

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.backup import object_restore
from apps.backup.models import BackupArchive, RestoreOperation, RestoreRollbackObject
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def restore_fixture():
    actor = User.objects.create_superuser(username="object-restore", password="secret")
    makerspace = Makerspace.objects.create(name="Object restore", slug="object-restore")
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        requested_by=actor,
        status=BackupArchive.Status.AVAILABLE,
        object_key="backup-archives/deployment/objects.tar.age",
        age_encrypted=True,
        expires_at=timezone.now() + timedelta(days=1),
    )
    restore = RestoreOperation.objects.create(
        archive=archive,
        kind=RestoreOperation.Kind.ROLLBACK_IN_PLACE,
        requested_by=actor,
    )
    return restore, makerspace


def test_unversioned_target_is_journalled_and_copied_before_overwrite(monkeypatch, tmp_path):
    restore, makerspace = restore_fixture()
    events = []

    class Client:
        def copy_object(self, **kwargs):
            assert RestoreRollbackObject.objects.filter(restore=restore).exists()
            events.append(("copy", kwargs["Key"]))
            return {"CopyObjectResult": {"ETag": "copy-etag"}}

    monkeypatch.setattr(object_restore.storage, "client", lambda: Client())
    monkeypatch.setattr(
        object_restore.storage,
        "ensure_versioning_or_quiescence",
        lambda _bucket: "quiesced",
    )
    monkeypatch.setattr(
        object_restore,
        "_head",
        lambda *_args: {"ContentLength": 42},
    )
    monkeypatch.setattr(
        object_restore,
        "_journal",
        lambda _path, payload: events.append((payload["effect"], payload.get("copy_key", ""))),
    )
    monkeypatch.setattr(object_restore.limits, "add_storage", lambda *_args: None)

    row = object_restore._prepare_rollback(
        restore,
        {
            "key": "events/one/image.jpg",
            "bucket_kind": RestoreRollbackObject.BucketKind.PRIVATE,
            "makerspace_id": makerspace.pk,
        },
        tmp_path / "journal.jsonl",
    )

    assert events[0][0] == "rollback_intent"
    assert events[1][0] == "copy"
    assert row.copy_key.startswith(f"rollback/{restore.pk}/")
    assert row.size_bytes == 42


def test_copy_failure_aborts_without_leaving_an_undo_claim(monkeypatch, tmp_path):
    restore, makerspace = restore_fixture()

    class Client:
        def copy_object(self, **_kwargs):
            raise OSError("copy unavailable")

    monkeypatch.setattr(object_restore.storage, "client", lambda: Client())
    monkeypatch.setattr(
        object_restore.storage,
        "ensure_versioning_or_quiescence",
        lambda _bucket: "quiesced",
    )
    monkeypatch.setattr(
        object_restore,
        "_head",
        lambda *_args: {"ContentLength": 42},
    )
    monkeypatch.setattr(object_restore, "_journal", lambda *_args: None)

    with pytest.raises(object_restore.ObjectRestoreError, match="nothing was overwritten"):
        object_restore._prepare_rollback(
            restore,
            {
                "key": "events/two/image.jpg",
                "bucket_kind": RestoreRollbackObject.BucketKind.PRIVATE,
                "makerspace_id": makerspace.pk,
            },
            tmp_path / "journal.jsonl",
        )
    assert not RestoreRollbackObject.objects.filter(restore=restore).exists()


def test_external_journal_probes_copy_created_immediately_before_interruption(
    monkeypatch, tmp_path
):
    restore, makerspace = restore_fixture()
    journal = tmp_path / "swap.jsonl"
    intent = {
        "effect": "rollback_intent",
        "row_id": 99,
        "bucket": "private-bucket",
        "bucket_kind": RestoreRollbackObject.BucketKind.PRIVATE,
        "makerspace_id": makerspace.pk,
        "module_key": "events",
        "source_key": "events/three/image.jpg",
        "copy_key": f"rollback/{restore.pk}/events/three/image.jpg",
        "absent": False,
        "source_version_id": "",
        "size_bytes": 0,
    }
    journal.write_text(json.dumps(intent) + "\n", encoding="utf-8")
    monkeypatch.setattr(object_restore.storage, "client", lambda: object())
    monkeypatch.setattr(object_restore, "_head", lambda *_args: None)
    assert object_restore.reconcile_rollback_journal(restore, journal) == 0

    monkeypatch.setattr(
        object_restore, "_head", lambda *_args: {"ContentLength": 73}
    )
    assert object_restore.reconcile_rollback_journal(restore, journal) == 1
    row = RestoreRollbackObject.objects.get(restore=restore)
    assert row.makerspace_id == makerspace.pk
    assert row.module_key == "events"
    assert row.size_bytes == 73


def test_versioned_rollback_detects_replacement_written_before_journal(
    monkeypatch,
):
    restore, _makerspace = restore_fixture()
    row = RestoreRollbackObject.objects.create(
        restore=restore,
        bucket_kind=RestoreRollbackObject.BucketKind.PRIVATE,
        source_key="events/four/image.jpg",
        source_version_id="original-version",
        replacement_version_id="",
        expires_at=timezone.now() + timedelta(days=7),
    )
    deleted = []

    class Client:
        def delete_object(self, **kwargs):
            deleted.append(kwargs)

    monkeypatch.setattr(object_restore.storage, "client", lambda: Client())
    monkeypatch.setattr(
        object_restore, "_head", lambda *_args: {"VersionId": "replacement-version"}
    )

    object_restore.rollback_objects(restore)

    assert deleted == [{
        "Bucket": object_restore.settings.AWS_STORAGE_BUCKET_NAME,
        "Key": row.source_key,
        "VersionId": "replacement-version",
    }]
