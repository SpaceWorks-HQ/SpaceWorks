import threading
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection

from apps.evidence import storage as evidence_storage
from apps.evidence.finalization import charge_storage_once
from apps.evidence.models import EvidencePhoto, EvidenceUploadFinalization
from apps.inventory import public_image_storage
from apps.makerspaces.models import Makerspace


def _photo(slug="post-finalize"):
    makerspace = Makerspace.objects.create(name=slug, slug=slug)
    uploader = get_user_model().objects.create_user(username=f"{slug}-uploader")
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/object",
        uploaded_by=uploader,
    )


def _fake_evidence_store(monkeypatch, objects):
    copied = []

    def validate(key):
        data = objects.get(key)
        if data is None:
            raise evidence_storage.EvidenceObjectValidationError("missing", "missing")
        return evidence_storage.EvidenceValidationResult(
            size=len(data), content_type="image/png"
        )

    def copy(source, destination):
        copied.append((source, destination))
        objects[destination] = objects[source]

    monkeypatch.setattr(evidence_storage, "validate_evidence_object", validate)
    monkeypatch.setattr(evidence_storage, "copy_object", copy)
    monkeypatch.setattr(evidence_storage, "delete_object", objects.pop)
    return copied


@pytest.mark.django_db
def test_post_presign_targets_staging_and_replay_cannot_replace_final(
    monkeypatch, settings
):
    settings.STORAGE_PRESIGN_METHOD = "post"
    photo = _photo()

    class FakePublicClient:
        def generate_presigned_post(self, *, Bucket, Key, Fields, Conditions, ExpiresIn):
            assert Bucket == settings.AWS_STORAGE_BUCKET_NAME
            assert Key == evidence_storage.staging_key(photo.object_key)
            assert Fields == {"Content-Type": "image/png"}
            assert {"Content-Type": "image/png"} in Conditions
            assert ["content-length-range", 1, settings.EVIDENCE_MAX_BYTES] in Conditions
            assert ExpiresIn == settings.EVIDENCE_URL_TTL_SECONDS
            return {"url": "http://minio/upload", "fields": {"key": Key, **Fields}}

    monkeypatch.setattr(evidence_storage, "_public_client", lambda: FakePublicClient())
    upload = evidence_storage.presigned_upload(photo.object_key, "image/png")
    assert upload["fields"]["key"] != photo.object_key

    objects = {upload["fields"]["key"]: b"original-image"}
    copied = _fake_evidence_store(monkeypatch, objects)
    first = evidence_storage.finalize_upload(photo, max_bytes=500)

    assert first.size == len(b"original-image")
    assert objects == {photo.object_key: b"original-image"}
    assert copied == [(evidence_storage.staging_key(photo.object_key), photo.object_key)]

    # The still-valid POST can only recreate staging. Idempotent finalization cleans
    # that replay and never copies it over the accepted final object.
    objects[upload["fields"]["key"]] = b"replacement-image"
    second = evidence_storage.finalize_upload(photo, max_bytes=500)

    assert second == first
    assert objects == {photo.object_key: b"original-image"}
    assert len(copied) == 1
    state = EvidenceUploadFinalization.objects.get(evidence=photo)
    assert state.status == EvidenceUploadFinalization.Status.FINALIZED


@pytest.mark.django_db(transaction=True)
def test_concurrent_post_finalization_promotes_exactly_once(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "post"
    photo = _photo("post-concurrent")
    staged_key = evidence_storage.staging_key(photo.object_key)
    objects = {staged_key: b"concurrent-image"}
    objects_lock = threading.Lock()
    copy_started = threading.Event()
    contender_checked = threading.Event()
    release_copy = threading.Event()
    copied = []

    def validate(key):
        with objects_lock:
            data = objects.get(key)
        if data is None:
            if threading.current_thread().name == "contender" and key == photo.object_key:
                contender_checked.set()
            raise evidence_storage.EvidenceObjectValidationError("missing", "missing")
        return evidence_storage.EvidenceValidationResult(
            size=len(data), content_type="image/png"
        )

    def copy(source, destination):
        assert connection.in_atomic_block is False
        copied.append((source, destination))
        copy_started.set()
        assert release_copy.wait(timeout=2)
        with objects_lock:
            objects[destination] = objects[source]

    def delete(key):
        with objects_lock:
            objects.pop(key, None)

    monkeypatch.setattr(evidence_storage, "validate_evidence_object", validate)
    monkeypatch.setattr(evidence_storage, "copy_object", copy)
    monkeypatch.setattr(evidence_storage, "delete_object", delete)
    results = []
    errors = []

    def run():
        close_old_connections()
        try:
            current = EvidencePhoto.objects.get(pk=photo.pk)
            results.append(evidence_storage.finalize_upload(current, max_bytes=500))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            close_old_connections()

    owner = threading.Thread(target=run, name="owner")
    contender = threading.Thread(target=run, name="contender")
    owner.start()
    assert copy_started.wait(timeout=2)
    contender.start()
    assert contender_checked.wait(timeout=2)
    release_copy.set()
    owner.join(timeout=3)
    contender.join(timeout=3)

    assert errors == []
    assert len(results) == 2
    assert copied == [(staged_key, photo.object_key)]
    assert objects == {photo.object_key: b"concurrent-image"}


@pytest.mark.django_db
def test_put_evidence_quota_is_charged_once(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"
    photo = _photo("put-quota-once")
    EvidenceUploadFinalization.objects.create(
        evidence=photo,
        status=EvidenceUploadFinalization.Status.FINALIZED,
        size_bytes=321,
        content_type="image/png",
    )
    add_storage = Mock()
    monkeypatch.setattr("apps.makerspaces.limits.add_storage", add_storage)

    charge_storage_once(photo, 321)
    charge_storage_once(photo, 321)

    add_storage.assert_called_once_with(photo.makerspace, 321)


def test_public_image_post_finalize_retries_transient_missing_object(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "post"
    attempts = []

    def fake_size(key):
        attempts.append(key)
        return None if len(attempts) == 1 else 123

    monkeypatch.setattr(public_image_storage, "object_size", fake_size)
    monkeypatch.setattr(public_image_storage.time, "sleep", lambda delay: None)

    result = public_image_storage.finalize_upload("printers/1/photo.png")

    assert result.status == "ok"
    assert result.size == 123
    assert attempts == ["printers/1/photo.png", "printers/1/photo.png"]


def test_public_image_finalize_uses_size_not_exists(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"
    settings.PUBLIC_IMAGE_MAX_BYTES = 500
    final_key = "items/1/object.jpg"
    staging_key = f"staging/{final_key}"
    copied = []
    sized = []

    def fake_size(key):
        sized.append(key)
        if key == final_key and not copied:
            return None
        return 123

    _block_object_exists(monkeypatch, public_image_storage)
    monkeypatch.setattr(public_image_storage, "object_size", fake_size)
    monkeypatch.setattr(public_image_storage, "copy_object", lambda source, dest: copied.append((source, dest)))
    monkeypatch.setattr(public_image_storage, "delete_object", lambda key: None)

    result = public_image_storage.finalize_upload(final_key)

    assert result.status == "ok"
    assert result.size == 123
    assert sized == [final_key, staging_key, final_key]
    assert copied == [(staging_key, final_key)]

def test_evidence_presigned_upload_put_mode_signs_staging_key(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"

    class FakePublicClient:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            assert operation == "put_object"
            assert Params == {
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": "staging/evidence/1/issue/x",
                "ContentType": "image/jpeg",
            }
            assert ExpiresIn == settings.EVIDENCE_URL_TTL_SECONDS
            return "http://minio/evidence-put"

    monkeypatch.setattr(
        "apps.evidence.storage._public_client",
        lambda: FakePublicClient(),
    )

    upload = evidence_storage.presigned_upload("evidence/1/issue/x", "image/jpeg")

    assert upload == {
        "url": "http://minio/evidence-put",
        "method": "PUT",
        "headers": {"Content-Type": "image/jpeg"},
    }

def _block_object_exists(monkeypatch, module):
    if hasattr(module, "object_exists"):
        monkeypatch.setattr(
            module,
            "object_exists",
            lambda key: pytest.fail("unexpected object_exists call"),
        )
