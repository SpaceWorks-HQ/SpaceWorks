from datetime import timedelta

from botocore.exceptions import ClientError
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.backup import archive_objects, storage
from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def make_photo(status):
    makerspace = Makerspace.objects.create(name=f"backup-{status}", slug=f"backup-{status}")
    user = get_user_model().objects.create_user(
        username=f"backup-{status}", email=f"backup-{status}@example.test"
    )
    photo = EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.pk}/photo.jpg",
        uploaded_by=user,
    )
    kwargs = {"evidence": photo, "status": status}
    if status == EvidenceObjectRetentionState.Status.EXPIRED:
        kwargs.update(
            object_expired_at=timezone.now() - timedelta(minutes=1),
            expired_size_bytes=456,
        )
    EvidenceObjectRetentionState.objects.create(**kwargs)
    return photo


def test_expired_evidence_is_captured_as_intentional_absence(tmp_path, monkeypatch):
    photo = make_photo(EvidenceObjectRetentionState.Status.EXPIRED)
    closure = {"private": {}, "public_image": {}}
    archive_objects.collect_model_objects(
        EvidencePhoto.objects.filter(pk=photo.pk), EvidencePhoto, closure
    )
    absent = []
    monkeypatch.setattr(
        storage, "assert_object_absent", lambda bucket, key: absent.append((bucket, key))
    )
    monkeypatch.setattr(
        storage,
        "download_object",
        lambda *_args, **_kwargs: pytest.fail("expired evidence attempted byte capture"),
    )

    manifest = archive_objects.capture_objects(
        tmp_path,
        closure,
        {"private": "versioned", "public_image": "versioned"},
    )

    assert absent == [
        (storage.settings.AWS_STORAGE_BUCKET_NAME, photo.object_key),
        (storage.settings.AWS_STORAGE_BUCKET_NAME, f"staging/{photo.object_key}"),
    ]
    assert manifest[0]["retention_state"] == "expired"
    assert manifest[0]["expired_size_bytes"] == 456
    assert manifest[0]["size"] == 0
    assert not (tmp_path / "private" / photo.object_key).exists()


def test_expiring_evidence_refuses_backup_capture():
    photo = make_photo(EvidenceObjectRetentionState.Status.EXPIRING)

    with pytest.raises(storage.BackupStorageError, match="in progress"):
        archive_objects.collect_model_objects(
            EvidencePhoto.objects.filter(pk=photo.pk),
            EvidencePhoto,
            {"private": {}, "public_image": {}},
        )


def test_cleaning_evidence_refuses_both_capture_paths():
    from apps.backup.object_reference_capture import build_object_ownership_plan
    from apps.backup.recipient_selection import BackupBuildError

    photo = make_photo(EvidenceObjectRetentionState.Status.CLEANING)

    with pytest.raises(storage.BackupStorageError, match="in progress"):
        archive_objects.collect_model_objects(
            EvidencePhoto.objects.filter(pk=photo.pk),
            EvidencePhoto,
            {"private": {}, "public_image": {}},
        )
    with pytest.raises(BackupBuildError, match="cleanup is in progress"):
        build_object_ownership_plan([photo.makerspace_id])


def test_cleaned_abandoned_upload_contributes_no_member_or_tombstone():
    from django.db import connection, transaction

    from apps.evidence.models import EvidenceAbandonedUploadReceipt

    photo = make_photo(EvidenceObjectRetentionState.Status.EXPIRED)
    EvidenceObjectRetentionState.objects.filter(evidence=photo).delete()
    unconsumed = EvidencePhoto.objects.create(
        makerspace=photo.makerspace, evidence_type="issue", object_key="evidence/gone/k",
        uploaded_by=photo.uploaded_by, consumption_state="unconsumed",
    )
    with transaction.atomic():
        EvidenceAbandonedUploadReceipt.objects.create(
            source_makerspace_id_snapshot=photo.makerspace_id,
            evidence_id_snapshot=unconsumed.pk, object_key=unconsumed.object_key,
            next_reconcile_at=timezone.now(),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [str(unconsumed.pk)])
        EvidencePhoto.objects.filter(pk=unconsumed.pk).delete()

    closure = archive_objects.object_closure()["private"]
    assert "evidence/gone/k" not in closure
    assert photo.object_key in closure and "retention_state" not in closure[photo.object_key]


def test_intentional_absence_requires_version_listing(monkeypatch):
    class Client:
        def list_object_versions(self, **_kwargs):
            raise ClientError(
                {"Error": {"Code": "NotImplemented", "Message": "unsupported"}},
                "ListObjectVersions",
            )

    monkeypatch.setattr(storage, "client", lambda: Client())

    with pytest.raises(storage.BackupStorageError, match="could not be inspected"):
        storage.assert_object_absent("private", "evidence/1/photo.jpg")
