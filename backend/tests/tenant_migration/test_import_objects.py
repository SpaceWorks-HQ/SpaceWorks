import hashlib
import json
from pathlib import Path

from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone
import pytest

from apps.audit.models import AuditLog
from apps.evidence.models import EvidencePhoto
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.models import Makerspace
from apps.tenant_migration import cutover, object_storage
from apps.tenant_migration.insertion_errors import ImportVerificationError
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.object_export import (
    SourceMigrationObjectError,
    capture_tenant_objects,
    object_member_path,
)
from apps.tenant_migration.object_verification import verify_import_objects
from apps.tenant_migration.services_import_job import cleanup_abandoned_import_objects
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import (
    PRIVATE_BYTES,
    PRIVATE_KEY,
    PUBLIC_BYTES,
    PUBLIC_KEY,
    encryption_key,
    memory_objects,
    pairing_and_receipt,
    prepare_source_objects,
    remove_source_evidence_after_archive,
    remove_source_object_footprint,
    write_object_bundle,
)
from tests.tenant_migration.protocol_helpers import superadmin
pytestmark = pytest.mark.django_db(transaction=True)


def test_private_and_public_objects_round_trip_and_stay_unservable_until_activation(
    memory_objects,
):
    with enabled_encryption():
        source_user = make_user("object-roundtrip")
        source = make_space("object-roundtrip")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            memory_objects["private"][PRIVATE_KEY] = PRIVATE_BYTES
            memory_objects["public_image"][PUBLIC_KEY] = PUBLIC_BYTES
            write_object_bundle(case.root)
            # The portable database archive and object bundle now own the source data.
            # Removing the source row and objects models a distinct target deployment
            # that has never seen either storage key, making preservation observable.
            remove_source_object_footprint(case, memory_objects)
            result = materialize_tenant(case.root, case.job, case.carried)
            target = Makerspace.objects.get(pk=result.target_makerspace_id)
            imported = EvidencePhoto.objects.get(makerspace=target)

            assert target.lifecycle_state == Makerspace.LifecycleState.IMPORTING
            assert imported.object_key == PRIVATE_KEY
            assert target.logo_key == PUBLIC_KEY
            with pytest.raises(Http404):
                get_public_makerspace(target.slug)
            assert memory_objects["private"][imported.object_key] == PRIVATE_BYTES
            assert memory_objects["public_image"][target.logo_key] == PUBLIC_BYTES
            assert len(
                [key for key in memory_objects["private"] if key.startswith("tenant-imports/")]
            ) == 2
            assert not any(
                key.startswith("tenant-imports/")
                for key in memory_objects["public_image"]
            )
            assert result.objects_promoted == 2
            assert result.object_keys_regenerated == 0
            assert result.object_key_regenerations == {}
            assert memory_objects["quota"] == [
                ("add", len(PRIVATE_BYTES)),
                ("add", len(PUBLIC_BYTES)),
            ]
            assert case.job.actor == source_user
            assert AuditLog.objects.filter(
                actor=source_user,
                action="tenant_migration.objects_promoted",
                target_id=str(case.job.pk),
            ).exists()

            actor = superadmin("object-activate")
            pairing, receipt = pairing_and_receipt(case.job, actor)
            cutover.activate_target(
                pairing=pairing,
                import_job=case.job,
                receipt_envelope=receipt,
                actor=actor,
            )

        target.refresh_from_db()
        assert get_public_makerspace(target.slug) == target
        assert target.lifecycle_state == Makerspace.LifecycleState.ACTIVE


def test_target_collision_regenerates_only_that_key(memory_objects):
    with enabled_encryption():
        source_user = make_user("object-collision")
        source = make_space("object-collision")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            memory_objects["private"][PRIVATE_KEY] = PRIVATE_BYTES
            memory_objects["public_image"][PUBLIC_KEY] = PUBLIC_BYTES
            write_object_bundle(case.root)
            # As above, discard the same-deployment source footprint after capture.
            # Then occupy only the public key on the simulated target: the private key
            # must be preserved while this one genuinely colliding key is regenerated.
            remove_source_object_footprint(case, memory_objects)
            memory_objects["public_image"][PUBLIC_KEY] = b"pre-existing target bytes"
            result = materialize_tenant(case.root, case.job, case.carried)

    target = Makerspace.objects.get(pk=result.target_makerspace_id)
    imported_private_key = EvidencePhoto.objects.get(makerspace=target).object_key
    assert target.logo_key != PUBLIC_KEY
    assert imported_private_key == PRIVATE_KEY
    assert memory_objects["public_image"][PUBLIC_KEY] == b"pre-existing target bytes"
    assert memory_objects["public_image"][target.logo_key] == PUBLIC_BYTES
    assert memory_objects["private"][imported_private_key] == PRIVATE_BYTES
    assert TenantImportObject.objects.get(
        job=case.job,
        source_key=PUBLIC_KEY,
    ).target_key == target.logo_key
    assert result.object_keys_regenerated == 1
    assert result.object_key_regenerations == {PUBLIC_KEY: target.logo_key}


def test_promotion_failure_rolls_back_final_and_staged_then_abort_blocks_activation(
    memory_objects, monkeypatch
):
    real_copy = object_storage.copy_from_staging

    def fail_public(staging_key, kind, target_key, content_type=""):
        if kind == "public_image":
            raise object_storage.TenantObjectStorageError("injected promotion failure")
        real_copy(staging_key, kind, target_key, content_type)

    monkeypatch.setattr(object_storage, "copy_from_staging", fail_public)
    with enabled_encryption():
        source_user = make_user("object-promotion-failure")
        source = make_space("object-promotion-failure")
        with portable_import_case(
            source, source_user, prepare_source=prepare_source_objects
        ) as case:
            case.decide_walk_in(source_user)
            write_object_bundle(case.root)
            with pytest.raises(object_storage.TenantObjectStorageError):
                materialize_tenant(case.root, case.job, case.carried)
            case.job.refresh_from_db()
            target = case.job.target_makerspace
            actor = superadmin("object-abort")
            pairing, receipt = pairing_and_receipt(case.job, actor)
            cutover.abort_target(pairing=pairing, import_job=case.job, actor=actor)

            assert not memory_objects["private"]
            assert not memory_objects["public_image"]
            assert memory_objects["quota"] == [
                ("add", len(PRIVATE_BYTES)),
                ("free", len(PRIVATE_BYTES)),
            ]
            assert set(case.job.import_objects.values_list("state", flat=True)) == {
                TenantImportObject.State.ROLLED_BACK
            }
            with pytest.raises(ImportVerificationError):
                cutover.activate_target(
                    pairing=pairing,
                    import_job=case.job,
                    receipt_envelope=receipt,
                    actor=actor,
                )

    target.refresh_from_db()
    assert target.lifecycle_state == Makerspace.LifecycleState.ABORTED


def test_pre_activation_rejects_unowned_and_checksum_mismatch(memory_objects):
    target = Makerspace.objects.create(
        name="Object Verify",
        slug="object-verify",
        lifecycle_state=Makerspace.LifecycleState.IMPORTING,
    )
    job = TenantImportJob.objects.create(
        source_archive_digest="f" * 64,
        target_makerspace=target,
        expires_at=timezone.now(),
    )
    orphan = TenantImportObject.objects.create(
        job=job,
        bucket_kind="private",
        source_key="orphan-source",
        staging_key=f"tenant-imports/{job.pk}/orphan",
        target_key="orphan-target",
        size=1,
        sha256=hashlib.sha256(b"x").hexdigest(),
        state=TenantImportObject.State.VERIFIED,
    )
    with pytest.raises(ImportVerificationError, match="no committed owner"):
        verify_import_objects(job)

    orphan.delete()
    target.logo_key = "owned-public"
    target.save(update_fields=("logo_key",))
    staging_key = f"tenant-imports/{job.pk}/owned"
    TenantImportObject.objects.create(
        job=job,
        bucket_kind="public_image",
        source_key="owned-public",
        staging_key=staging_key,
        target_key="owned-public",
        size=4,
        sha256=hashlib.sha256(b"good").hexdigest(),
        state=TenantImportObject.State.VERIFIED,
    )
    memory_objects["private"][staging_key] = b"good"
    memory_objects["public_image"]["owned-public"] = b"bad!"
    with pytest.raises(ImportVerificationError, match="checksum mismatch"):
        verify_import_objects(job)
    target.refresh_from_db()
    assert target.lifecycle_state == Makerspace.LifecycleState.IMPORTING


def test_missing_enumerated_source_object_aborts_export(tmp_path, monkeypatch):
    source = make_space("missing-source-object")
    monkeypatch.setattr(
        "apps.tenant_migration.object_export.collect_private_object_keys",
        lambda *_args, **_kwargs: [PRIVATE_KEY],
    )
    monkeypatch.setattr(
        "apps.tenant_migration.object_export.collect_public_image_keys",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "apps.tenant_migration.object_export.storage.download_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    with pytest.raises(SourceMigrationObjectError, match=PRIVATE_KEY):
        capture_tenant_objects(
            tmp_path,
            source,
            {"private": "quiesced", "public_image": "quiesced"},
        )


def test_export_layout_streams_opaque_members_and_version_manifest(tmp_path, monkeypatch):
    source = make_space("object-export-layout")
    monkeypatch.setattr(
        "apps.tenant_migration.object_export.collect_private_object_keys",
        lambda *_args, **_kwargs: [PRIVATE_KEY],
    )
    monkeypatch.setattr(
        "apps.tenant_migration.object_export.collect_public_image_keys",
        lambda *_args, **_kwargs: [PUBLIC_KEY],
    )
    calls = []

    def download(bucket, key, destination, *, versioned):
        data = PRIVATE_BYTES if key == PRIVATE_KEY else PUBLIC_BYTES
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        calls.append((bucket, key, versioned))
        return {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "version_id": "pinned-v1" if versioned else "",
            "content_type": "application/pdf" if key == PRIVATE_KEY else "image/png",
        }

    monkeypatch.setattr(
        "apps.tenant_migration.object_export.storage.download_object", download
    )
    records = capture_tenant_objects(
        tmp_path,
        source,
        {"private": "versioned", "public_image": "quiesced"},
    )

    assert (tmp_path / object_member_path("private", PRIVATE_KEY)).read_bytes() == PRIVATE_BYTES
    assert (tmp_path / object_member_path("public_image", PUBLIC_KEY)).read_bytes() == PUBLIC_BYTES
    lines = [
        json.loads(line)
        for line in Path(tmp_path, "objects", "manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert lines == records
    assert records[0]["version_id"] == "pinned-v1"
    assert records[1]["version_id"] is None
    assert records[0]["content_type"] == "application/pdf"
    assert records[1]["content_type"] == "image/png"
    assert [call[2] for call in calls] == [True, False]


def test_abandoned_object_cleanup_is_leased_and_idempotent(memory_objects):
    job = TenantImportJob.objects.create(
        source_archive_digest="a" * 64,
        status=TenantImportJob.Status.ABANDONED,
        expires_at=timezone.now(),
    )
    staging_key = f"tenant-imports/{job.pk}/abandoned"
    memory_objects["private"][staging_key] = b"staged"
    row = TenantImportObject.objects.create(
        job=job,
        bucket_kind="private",
        source_key="abandoned",
        staging_key=staging_key,
        target_key="abandoned",
        size=6,
        sha256=hashlib.sha256(b"staged").hexdigest(),
    )
    now = timezone.now()

    assert cleanup_abandoned_import_objects(now=now) == 1
    assert cleanup_abandoned_import_objects(now=now) == 0
    row.refresh_from_db()
    assert row.state == TenantImportObject.State.ROLLED_BACK
    assert not memory_objects["private"]
