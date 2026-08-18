from datetime import timedelta
import hashlib
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from django.db import OperationalError
from django.utils import timezone
import pytest

from apps.makerspaces.models import Makerspace
from apps.tenant_migration import object_promotion, object_storage, promotion_lease
from apps.tenant_migration.models import TenantImportJob, TenantImportObject
from apps.tenant_migration.object_export import object_member_path
from apps.tenant_migration.object_import import (
    prepare_import_objects,
    promote_import_objects,
)
from tests.tenant_migration.object_helpers import memory_objects
from tests.tenant_migration.protocol_helpers import superadmin


pytestmark = pytest.mark.django_db(transaction=True)


def _write_bundle(root, records):
    for record, data in records:
        member = Path(root) / object_member_path(
            record["bucket_kind"], record["source_key"]
        )
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(data)
        record.update(
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            version_id=None,
        )
    manifest = Path(root, "objects", "manifest.jsonl")
    manifest.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record, _ in records),
        encoding="utf-8",
    )


def _import_job(name):
    target = Makerspace.objects.create(name=name, slug=name)
    return TenantImportJob.objects.create(
        source_archive_digest="c" * 64,
        target_makerspace=target,
        actor=superadmin(f"{name}-actor"),
        expires_at=timezone.now(),
    )


def test_promotion_restores_public_image_and_private_document_content_types(
    tmp_path, memory_objects
):
    records = [
        (
            {
                "bucket_kind": "private",
                "source_key": "machine-documents/source/manual.pdf",
                "content_type": "application/pdf",
            },
            b"private document",
        ),
        (
            {
                "bucket_kind": "public_image",
                "source_key": "makerspace/source/logo.png",
                "content_type": "image/png",
            },
            b"public image",
        ),
    ]
    _write_bundle(tmp_path, records)
    job = _import_job("mime-roundtrip")

    prepare_import_objects(SimpleNamespace(root=tmp_path), job)
    assert list(
        job.import_objects.order_by("bucket_kind").values_list("content_type", flat=True)
    ) == ["application/pdf", "image/png"]
    assert promote_import_objects(job) == 2

    assert memory_objects["content_types"]["private"][
        "machine-documents/source/manual.pdf"
    ] == "application/pdf"
    assert memory_objects["content_types"]["public_image"][
        "makerspace/source/logo.png"
    ] == "image/png"


def test_promotion_without_source_content_type_uses_storage_default(
    tmp_path, memory_objects
):
    source_key = "machine-documents/source/legacy"
    records = [
        (
            {"bucket_kind": "private", "source_key": source_key},
            b"legacy document",
        )
    ]
    _write_bundle(tmp_path, records)
    job = _import_job("mime-fallback")

    prepare_import_objects(SimpleNamespace(root=tmp_path), job)
    row = TenantImportObject.objects.get(job=job)
    assert row.content_type == ""
    assert promote_import_objects(job) == 1
    assert (
        memory_objects["content_types"]["private"][source_key]
        == "application/octet-stream"
    )


def test_promotion_heartbeat_database_error_defers_to_claim_fence(
    tmp_path, memory_objects, monkeypatch, caplog
):
    source_key = "machine-documents/source/heartbeat.pdf"
    _write_bundle(
        tmp_path,
        [
            (
                {
                    "bucket_kind": "private",
                    "source_key": source_key,
                    "content_type": "application/pdf",
                },
                b"heartbeat survives",
            ),
        ],
    )
    job = _import_job("heartbeat-database-error")
    prepare_import_objects(SimpleNamespace(root=tmp_path), job)
    heartbeat_failed = Event()

    class FailedRenewal:
        def update(self, **_kwargs):
            heartbeat_failed.set()
            raise OperationalError("transient heartbeat failure")

    class FailedRenewalManager:
        @staticmethod
        def filter(**_kwargs):
            return FailedRenewal()

    class HeartbeatImportObject:
        State = TenantImportObject.State
        objects = FailedRenewalManager()

    real_copy = object_storage.copy_from_staging

    def copy_after_failed_heartbeat(*args):
        assert heartbeat_failed.wait(timeout=2)
        return real_copy(*args)

    monkeypatch.setattr(
        promotion_lease, "TenantImportObject", HeartbeatImportObject
    )
    monkeypatch.setattr(
        object_promotion, "PROMOTION_LEASE_DURATION", timedelta(milliseconds=30)
    )
    monkeypatch.setattr(
        object_storage, "copy_from_staging", copy_after_failed_heartbeat
    )

    with caplog.at_level("WARNING"):
        assert promote_import_objects(job) == 1

    row = TenantImportObject.objects.get(job=job)
    assert row.state == TenantImportObject.State.VERIFIED
    assert memory_objects["private"][source_key] == b"heartbeat survives"
    assert "tenant_import_promotion_heartbeat_failed" in caplog.text


def test_storage_copy_replaces_only_known_content_type(settings, monkeypatch):
    calls = []
    fake_client = SimpleNamespace(copy_object=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(object_storage, "client", lambda: fake_client)
    settings.AWS_STORAGE_BUCKET_NAME = "private-bucket"
    settings.PUBLIC_IMAGE_BUCKET = "public-bucket"

    object_storage.copy_from_staging(
        "staged-private", "private", "manual.pdf", "application/pdf"
    )
    object_storage.copy_from_staging(
        "staged-public", "public_image", "logo.png", "image/png"
    )
    object_storage.copy_from_staging("staged-legacy", "private", "legacy")

    assert calls[0]["ContentType"] == "application/pdf"
    assert calls[0]["MetadataDirective"] == "REPLACE"
    assert calls[1]["ContentType"] == "image/png"
    assert calls[1]["MetadataDirective"] == "REPLACE"
    assert "ContentType" not in calls[2]
    assert "MetadataDirective" not in calls[2]


def test_promotion_heartbeat_keeps_renewing_after_a_transient_failure(
    tmp_path, memory_objects, monkeypatch, caplog
):
    """One bad renewal must drop a beat, not abandon the lease.

    Abandoning renewal leaves a live worker looking stale to the recovery sweep,
    which then starts a second worker and duplicates the object copy. The fenced
    promotion write still keeps the journal correct, so the damage is wasted
    external work rather than corruption -- which is exactly what retrying avoids.
    """
    source_key = "machine-documents/source/retry.pdf"
    _write_bundle(
        tmp_path,
        [
            (
                {
                    "bucket_kind": "private",
                    "source_key": source_key,
                    "content_type": "application/pdf",
                },
                b"heartbeat retries",
            ),
        ],
    )
    job = _import_job("heartbeat-retry")
    prepare_import_objects(SimpleNamespace(root=tmp_path), job)

    real_manager = TenantImportObject.objects
    attempts = []
    renewed_again = Event()

    class RetryingRenewal:
        def __init__(self, filters):
            self.filters = filters

        def update(self, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise OperationalError("transient heartbeat failure")
            result = real_manager.filter(**self.filters).update(**kwargs)
            renewed_again.set()
            return result

    class RetryingManager:
        @staticmethod
        def filter(**filters):
            return RetryingRenewal(filters)

    class HeartbeatImportObject:
        State = TenantImportObject.State
        objects = RetryingManager()

    real_copy = object_storage.copy_from_staging

    def copy_after_second_renewal(*args):
        assert renewed_again.wait(timeout=5), "heartbeat stopped after one failure"
        return real_copy(*args)

    monkeypatch.setattr(promotion_lease, "TenantImportObject", HeartbeatImportObject)
    monkeypatch.setattr(
        object_promotion, "PROMOTION_LEASE_DURATION", timedelta(milliseconds=30)
    )
    monkeypatch.setattr(
        object_storage, "copy_from_staging", copy_after_second_renewal
    )

    with caplog.at_level("WARNING"):
        assert promote_import_objects(job) == 1

    assert len(attempts) >= 2
    assert TenantImportObject.objects.get(job=job).state == (
        TenantImportObject.State.VERIFIED
    )
    assert "tenant_import_promotion_heartbeat_failed" in caplog.text
