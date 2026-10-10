from pathlib import Path

import pytest

from apps.tenant_migration.object_import import _validate_record
from apps.tenant_migration.insertion_errors import ArchiveFormatError
from apps.tenant_migration.tenant_dump_objects import package_staged_objects


def tombstone():
    return {
        "bucket_kind": "private",
        "source_key": "evidence/1/photo.jpg",
        "size": 0,
        "sha256": "",
        "version_id": None,
        "content_type": "",
        "retention_state": "expired",
        "object_expired_at": "2026-09-02T10:00:00+00:00",
        "expired_size_bytes": 789,
    }


def test_portable_manifest_accepts_only_a_complete_expiry_tombstone():
    _validate_record(tombstone(), 1)
    incomplete = tombstone()
    incomplete.pop("object_expired_at")

    with pytest.raises(ArchiveFormatError, match="Incomplete expiry tombstone"):
        _validate_record(incomplete, 1)


def test_lane_d_tombstone_packages_without_object_bytes(tmp_path):
    entry = {
        **tombstone(),
        "original_key": "evidence/1/photo.jpg",
        "member_path": None,
    }

    manifest = package_staged_objects(tmp_path / "capture", tmp_path / "bundle", [entry])

    assert manifest == ({
        "bucket_kind": "private",
        "member_path": None,
        "original_key": "evidence/1/photo.jpg",
        "version_id": None,
        "size": 0,
        "content_type": "",
        "sha256": "",
        "retention_state": "expired",
        "object_expired_at": "2026-09-02T10:00:00+00:00",
        "expired_size_bytes": 789,
    },)
    assert not Path(tmp_path / "bundle" / "objects").exists()


@pytest.mark.django_db
def test_tenant_export_refuses_an_upload_being_cleaned(tmp_path):
    from django.contrib.auth import get_user_model

    from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto
    from apps.makerspaces.models import Makerspace
    from apps.tenant_migration.object_export import (
        SourceMigrationObjectError,
        capture_tenant_objects,
    )

    makerspace = Makerspace.objects.create(name="tm-cleaning", slug="tm-cleaning")
    user = get_user_model().objects.create_user(username="tm-cleaning", email="tm@e.test")
    photo = EvidencePhoto.objects.create(
        makerspace=makerspace, evidence_type="issue", object_key="evidence/tm/cleaning",
        uploaded_by=user,
    )
    EvidenceObjectRetentionState.objects.create(
        evidence=photo, status=EvidenceObjectRetentionState.Status.CLEANING
    )
    with pytest.raises(SourceMigrationObjectError, match="abandoned upload"):
        capture_tenant_objects(tmp_path, makerspace, {"private": "versioned", "public_image": "versioned"})


@pytest.mark.django_db(transaction=True)
def test_concurrent_photo_insert_cannot_take_a_key_a_receipt_is_reserving():
    """Receipt INSERT holds the exact-key advisory lock; a racing photo INSERT waits, then fails."""
    import threading

    from django.contrib.auth import get_user_model
    from django.db import Error, connection, connections, transaction
    from django.utils import timezone

    from apps.evidence.models import EvidenceAbandonedUploadReceipt, EvidencePhoto
    from apps.makerspaces.models import Makerspace

    makerspace = Makerspace.objects.create(name="tm-race", slug="tm-race")
    user = get_user_model().objects.create_user(username="tm-race", email="tmr@e.test")
    photo = EvidencePhoto.objects.create(
        makerspace=makerspace, evidence_type="issue", object_key="evidence/race/k",
        uploaded_by=user, consumption_state="unconsumed",
    )
    outcome = {}
    receipt_inserted = threading.Event()

    def importer():
        receipt_inserted.wait(10)
        try:
            with transaction.atomic():
                EvidencePhoto.objects.create(
                    makerspace=makerspace, evidence_type="issue",
                    object_key="evidence/race/k", uploaded_by=user,
                )
            outcome["result"] = "inserted"
        except Error as exc:
            outcome["result"] = type(exc).__name__
        finally:
            connections.close_all()

    thread = threading.Thread(target=importer)
    thread.start()
    with transaction.atomic():
        EvidenceAbandonedUploadReceipt.objects.create(
            source_makerspace_id_snapshot=makerspace.pk, evidence_id_snapshot=photo.pk,
            object_key=photo.object_key, next_reconcile_at=timezone.now(),
        )
        receipt_inserted.set()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_sleep(0.5)")
            cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [str(photo.pk)])
        EvidencePhoto.objects.filter(pk=photo.pk).delete()
    thread.join(20)
    assert outcome["result"] != "inserted"
    assert not EvidencePhoto.objects.filter(object_key="evidence/race/k").exists()
