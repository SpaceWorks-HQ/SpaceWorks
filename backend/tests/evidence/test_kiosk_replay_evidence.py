from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.evidence import storage
from apps.evidence.models import EvidencePhoto, EvidenceObjectRetentionState
from apps.hardware_requests.models import ReplayCommand
from apps.hardware_requests.replay_cleanup import cleanup_replay_commands
from tests.hardware_requests.replay_helpers import envelope, execute, prepare, replay_env

pytestmark = pytest.mark.django_db


def test_prepare_presigns_same_staging_photo_on_retry_and_rejects_metadata_conflict(replay_env):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    one, two = prepare(env, data), prepare(env, data)
    assert one.status_code == two.status_code == 200
    assert one.data["evidence_id"] == two.data["evidence_id"]
    photo = EvidencePhoto.objects.get()
    assert photo.uploaded_by == env.user and photo.makerspace == env.space
    assert one.data["upload"]["fields"]["key"] == f"staging/{photo.object_key}"
    data["evidence"]["size_bytes"] = 124
    assert prepare(env, data).data["code"] == "idempotency_conflict"
    assert EvidencePhoto.objects.count() == 1


def test_storage_failure_rolls_back_prepare_and_leaves_execute_retryable(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    def down(*args):
        raise storage.StorageUnavailable("private storage error")
    with monkeypatch.context() as patch:
        patch.setattr("apps.evidence.services_upload.presigned_upload", down)
        response = prepare(env, data)
    assert response.status_code == 503 and response.data["code"] == "storage_unavailable"
    assert not ReplayCommand.objects.exists() and not EvidencePhoto.objects.exists()
    assert prepare(env, data).status_code == 200
    with monkeypatch.context() as patch:
        patch.setattr("apps.evidence.storage.finalize_upload", down)
        response = execute(env, data)
    assert response.status_code == 503 and ReplayCommand.objects.get().state == "prepared"
    from apps.audit.models import AuditLog
    assert AuditLog.objects.filter(action="kiosk.replay_claimed", actor=env.user).exists()
    assert "private storage" not in str(response.data)


@pytest.mark.parametrize("storage_code,failure", [("missing", "evidence_missing"), ("invalid_image", "evidence_invalid"), ("expired", "evidence_invalid")])
def test_invalid_or_absent_upload_is_terminal_and_retains_photo(replay_env, monkeypatch, storage_code, failure):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    def refuse(*args):
        raise storage.EvidenceObjectValidationError(storage_code, "never expose raw text")
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", refuse)
    response = execute(env, data)
    assert response.data["code"] == failure
    command = ReplayCommand.objects.get()
    assert command.state == "failed" and command.evidence_id == EvidencePhoto.objects.get().pk


def test_finalized_reuse_inside_domain_transaction_has_no_storage_io(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    photo = EvidencePhoto.objects.get()
    storage.finalize_upload(photo, 1000)
    def forbidden(*args):
        raise AssertionError("storage I/O under a domain lock")
    monkeypatch.setattr(storage, "delete_object", forbidden)
    monkeypatch.setattr(storage, "copy_object", forbidden)
    monkeypatch.setattr(storage, "validate_evidence_object", forbidden)
    monkeypatch.setattr("apps.evidence.finalization.lock_evidence_for_attachment", forbidden)
    with transaction.atomic():
        result = storage.finalize_upload(photo, 1000)
    assert result.size == 123


def test_failed_qr_photo_is_readable_and_cleanup_keeps_it(replay_env, monkeypatch):
    from tests.events.checkin_helpers import make_member
    env = replay_env
    member = make_member(env.space)
    monkeypatch.setattr("apps.hardware_requests.direct_loan_workflow.require_active_member_presence", lambda *args: SimpleNamespace(membership=None))
    data = envelope(env, "direct_handout", {"borrower_id": member.pk, "qr_payloads": ["revoked-or-foreign"]})
    assert prepare(env, data).status_code == 200
    response = execute(env, data)
    assert response.data["code"] == "qr_revoked"
    command = ReplayCommand.objects.get()
    photo = command.evidence
    reader = APIClient()
    reader.force_authenticate(env.user)
    monkeypatch.setattr("apps.evidence.views.presigned_get_url", lambda key: f"https://storage.test/{key}")
    read = reader.get(reverse("evidence_admin:evidence-detail", kwargs={"pk": photo.pk}))
    assert read.status_code == 200, read.data
    cleanup_replay_commands(now=timezone.now() + timedelta(days=8))
    assert not ReplayCommand.objects.exists() and EvidencePhoto.objects.filter(pk=photo.pk).exists()


def test_unconsumed_failure_reads_staging_and_expired_state_never_reads_storage(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    photo = EvidencePhoto.objects.get()
    reader = APIClient()
    reader.force_authenticate(env.user)
    seen = []
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda key: key.startswith("staging/"))
    def signed(key):
        seen.append(key)
        return "https://storage.test/evidence"
    monkeypatch.setattr("apps.evidence.views.presigned_get_url", signed)
    url = reverse("evidence_admin:evidence-detail", kwargs={"pk": photo.pk})
    assert reader.get(url).status_code == 200
    assert seen == [storage.staging_key(photo.object_key)]
    EvidenceObjectRetentionState.objects.create(evidence=photo, status="expired", object_expired_at=timezone.now())
    seen.clear()
    monkeypatch.setattr("apps.evidence.views.object_exists", lambda key: pytest.fail("expired evidence consulted storage"))
    assert reader.get(url).status_code == 410 and seen == []


def test_staging_promotion_happens_once_and_later_staging_bytes_cannot_replace_final(replay_env, monkeypatch):
    env = replay_env
    data = envelope(env, "reviewed_issue", {"request_id": env.request.pk})
    assert prepare(env, data).status_code == 200
    photo = EvidencePhoto.objects.get()
    staging = storage.staging_key(photo.object_key)
    objects, copies = {staging: 123}, []
    def validate(key):
        if key not in objects:
            raise storage.EvidenceObjectValidationError("missing", "not uploaded")
        return storage.EvidenceValidationResult(size=objects[key], content_type="image/jpeg")
    def copy(source, target):
        copies.append((source, target))
        objects[target] = objects[source]
    monkeypatch.setattr(storage, "validate_evidence_object", validate)
    monkeypatch.setattr(storage, "copy_object", copy)
    monkeypatch.setattr(storage, "delete_object", lambda key: objects.pop(key, None))
    assert execute(env, data).data["code"] == "box_scan_required"
    assert copies == [(staging, photo.object_key)]
    objects[staging] = 456
    assert storage.finalize_upload(photo, 1000).size == 123
    assert objects[photo.object_key] == 123 and len(copies) == 1
