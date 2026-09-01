from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.evidence import finalization, storage
from apps.evidence.models import (
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
    EvidenceUploadFinalization,
)
from apps.evidence.services_retention import sweep_evidence_retention
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_manager(slug, makerspace):
    user = get_user_model().objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def make_photo(makerspace, uploader, *, key="evidence/retention/photo.jpg", size=123):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=key,
        content_type="image/jpeg",
        size_bytes=size,
        uploaded_by=uploader,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def policy_url(makerspace):
    return reverse(
        "evidence_admin:evidence-retention-policy",
        kwargs={"makerspace_id": makerspace.pk},
    )


def preview_url(makerspace):
    return reverse(
        "evidence_admin:evidence-retention-preview",
        kwargs={"makerspace_id": makerspace.pk},
    )


def test_manager_can_set_preview_and_clear_object_retention(settings):
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 365
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = False
    makerspace = make_space("retention-policy")
    manager = make_manager("retention-policy-manager", makerspace)
    photo = make_photo(makerspace, manager)
    as_of = timezone.now() + timedelta(days=90)
    EvidenceRetentionPolicy.objects.create(
        makerspace=makerspace, object_retention_days=60
    )

    response = client_for(manager).get(policy_url(makerspace))
    assert response.status_code == 200
    assert response.data == {
        "makerspace_id": makerspace.pk,
        "platform_default_days": 365,
        "override_days": 60,
        "effective_days": 60,
        "object_expiry_enabled": False,
    }

    response = client_for(manager).post(
        preview_url(makerspace), {"limit": 100}, format="json"
    )
    assert response.status_code == 200
    assert response.data["policy_days"] == 60
    assert response.data["object_candidates"] == 0

    # Exercise the exact boundary independently of wall-clock API time.
    from apps.evidence.retention_policy import preview_object_expiry

    preview = preview_object_expiry(makerspace, limit=100, as_of=as_of)
    assert preview["object_candidates"] == 1
    assert preview["candidate_bytes"] == photo.size_bytes

    response = client_for(manager).patch(
        policy_url(makerspace), {"object_retention_days": None}, format="json"
    )
    assert response.status_code == 200
    assert response.data["override_days"] is None
    assert response.data["effective_days"] == 365
    assert not EvidenceRetentionPolicy.objects.filter(makerspace=makerspace).exists()
    assert AuditLog.objects.filter(action="evidence.retention_policy_updated").count() == 1


def test_non_event_manager_cannot_change_policy():
    makerspace = make_space("retention-rbac")
    user = get_user_model().objects.create_user(
        username="retention-inventory",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )

    response = client_for(user).patch(
        policy_url(makerspace), {"object_retention_days": 90}, format="json"
    )

    assert response.status_code == 403
    assert not EvidenceRetentionPolicy.objects.exists()


def test_disabled_sweep_has_no_side_effects(settings, monkeypatch):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = False
    makerspace = make_space("retention-disabled")
    manager = make_manager("retention-disabled-manager", makerspace)
    make_photo(makerspace, manager)
    monkeypatch.setattr(
        "apps.evidence.storage.object_size",
        lambda _key: pytest.fail("disabled expiry touched storage"),
    )

    summary = sweep_evidence_retention(now=timezone.now() + timedelta(days=400))

    assert summary["photos_expired"] == 0
    assert not EvidenceObjectRetentionState.objects.exists()
    assert not AuditLog.objects.filter(action="evidence.object_expired").exists()


def test_dry_run_selects_candidates_without_mutation(settings, monkeypatch):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    makerspace = make_space("retention-dry-run")
    manager = make_manager("retention-dry-run-manager", makerspace)
    make_photo(makerspace, manager)
    monkeypatch.setattr(
        "apps.evidence.storage.object_size",
        lambda _key: pytest.fail("dry run touched storage"),
    )

    summary = sweep_evidence_retention(
        dry_run=True, now=timezone.now() + timedelta(days=31)
    )

    assert summary["photos_eligible"] == 1
    assert summary["bytes_removed"] == 0
    assert not EvidenceObjectRetentionState.objects.exists()
    assert not AuditLog.objects.filter(action="evidence.object_expired").exists()


def test_enabled_sweep_deletes_both_keys_retains_row_and_releases_quota(
    settings, monkeypatch
):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 365
    settings.EVIDENCE_RETENTION_BATCH_SIZE = 100
    settings.STORAGE_PRESIGN_METHOD = "put"
    makerspace = make_space("retention-enabled")
    manager = make_manager("retention-enabled-manager", makerspace)
    photo = make_photo(makerspace, manager, size=321)
    EvidenceUploadFinalization.objects.create(
        evidence=photo,
        status=EvidenceUploadFinalization.Status.FINALIZED,
        size_bytes=321,
        content_type="image/jpeg",
        quota_charged=True,
    )
    Makerspace.objects.filter(pk=makerspace.pk).update(storage_bytes_used=321)
    monkeypatch.setattr("apps.makerspaces.limits.is_self_host", lambda: False)
    monkeypatch.setattr(storage, "object_size", lambda _key: 321)
    deleted = []
    monkeypatch.setattr(
        storage,
        "delete_object_strict",
        lambda key: deleted.append(key) or "deleted",
    )

    summary = sweep_evidence_retention(now=timezone.now() + timedelta(days=366))

    assert deleted == [photo.object_key, storage.staging_key(photo.object_key)]
    assert summary["photos_expired"] == 1
    assert summary["bytes_removed"] == 321
    assert EvidencePhoto.objects.filter(pk=photo.pk).exists()
    state = EvidenceObjectRetentionState.objects.get(evidence=photo)
    assert state.status == EvidenceObjectRetentionState.Status.EXPIRED
    assert state.expired_size_bytes == 321
    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 0
    assert AuditLog.objects.filter(
        action="evidence.object_expired", target_id=str(photo.pk)
    ).count() == 1


def test_storage_failure_is_retryable_and_does_not_release_quota(settings, monkeypatch):
    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    settings.EVIDENCE_OBJECT_RETENTION_DAYS = 30
    settings.STORAGE_PRESIGN_METHOD = "put"
    makerspace = make_space("retention-retry")
    manager = make_manager("retention-retry-manager", makerspace)
    photo = make_photo(makerspace, manager, size=75)
    EvidenceUploadFinalization.objects.create(
        evidence=photo,
        status=EvidenceUploadFinalization.Status.FINALIZED,
        size_bytes=75,
        quota_charged=True,
    )
    Makerspace.objects.filter(pk=makerspace.pk).update(storage_bytes_used=75)
    monkeypatch.setattr("apps.makerspaces.limits.is_self_host", lambda: False)
    monkeypatch.setattr(storage, "object_size", lambda _key: 75)
    monkeypatch.setattr(
        storage,
        "delete_object_strict",
        lambda _key: (_ for _ in ()).throw(storage.StorageUnavailable()),
    )

    summary = sweep_evidence_retention(now=timezone.now() + timedelta(days=31))

    assert summary["photos_failed"] == 1
    state = EvidenceObjectRetentionState.objects.get(evidence=photo)
    assert state.status == EvidenceObjectRetentionState.Status.EXPIRING
    assert state.claim_token is None
    assert state.last_error.startswith("StorageUnavailable")
    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 75
    assert not AuditLog.objects.filter(action="evidence.object_expired").exists()


def test_expired_detail_returns_410_without_storage_access(monkeypatch):
    makerspace = make_space("retention-gone")
    manager = make_manager("retention-gone-manager", makerspace)
    photo = make_photo(makerspace, manager)
    expired_at = timezone.now()
    EvidenceObjectRetentionState.objects.create(
        evidence=photo,
        status=EvidenceObjectRetentionState.Status.EXPIRED,
        object_expired_at=expired_at,
        expired_size_bytes=123,
    )
    monkeypatch.setattr(
        "apps.evidence.views.object_exists",
        lambda _key: pytest.fail("expired detail touched storage"),
    )

    response = client_for(manager).get(
        reverse("evidence_admin:evidence-detail", kwargs={"pk": photo.pk})
    )

    assert response.status_code == 410
    assert response.data["code"] == "evidence_expired"
    assert response.data["object_expired_at"] is not None


def test_finalization_rejects_an_expiring_photo():
    makerspace = make_space("retention-finalize")
    manager = make_manager("retention-finalize-manager", makerspace)
    photo = make_photo(makerspace, manager)
    EvidenceObjectRetentionState.objects.create(evidence=photo)

    with pytest.raises(storage.EvidenceObjectValidationError) as exc:
        finalization._claim(photo.pk)

    assert exc.value.code == "expired"
