"""Abandoned-upload cleanup: candidates, state machine, quota, audit, receipts, guards."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import Error, connection, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.accounts.models import User
from apps.audit import services as audit
from apps.audit.models import AuditLog
from apps.evidence import storage
from apps.evidence.abandoned_upload_cleanup import sweep_abandoned_evidence_uploads
from apps.evidence.abandoned_upload_reconciliation import (
    FAILURE_BACKOFF,
    SUCCESS_INTERVAL,
    reconcile_receipts,
)
from apps.evidence.models import (
    EvidenceAbandonedUploadReceipt,
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
    EvidenceUploadFinalization,
)
from apps.evidence.services_retention import sweep_evidence_retention
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db
C = EvidencePhoto.ConsumptionState
S = EvidenceObjectRetentionState.Status
LATER = timedelta(days=30)


def space(slug, *, opt_in=True, days=None):
    makerspace = Makerspace.objects.create(name=slug, slug=slug)
    if opt_in or days:
        EvidenceRetentionPolicy.objects.create(
            makerspace=makerspace,
            abandoned_upload_cleanup_enabled=opt_in,
            abandoned_upload_retention_days=days,
        )
    return makerspace


def photo(makerspace, *, state=C.UNCONSUMED, key=None, size=50):
    user, _ = get_user_model().objects.get_or_create(
        username=f"{makerspace.slug}-uploader",
        defaults={"email": f"{makerspace.slug}@e.test", "role": User.Role.SPACE_MANAGER},
    )
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=key or f"evidence/{makerspace.pk}/issue/{makerspace.slug}-{EvidencePhoto.objects.count()}",
        content_type="image/jpeg",
        size_bytes=size,
        uploaded_by=user,
        consumption_state=state,
    )


@pytest.fixture
def fake_storage(monkeypatch, settings):
    settings.EVIDENCE_ABANDONED_UPLOAD_CLEANUP_ENABLED = True
    settings.EVIDENCE_ABANDONED_UPLOAD_RETENTION_DAYS = 7
    calls = {"deleted": [], "fail": set()}

    def delete(key):
        if key in calls["fail"]:
            raise storage.StorageUnavailable("boom")
        calls["deleted"].append(key)
        return "absent_or_version_only"

    monkeypatch.setattr(storage, "object_size", lambda _key: None)
    monkeypatch.setattr(storage, "delete_object_strict", delete)
    return calls


def run(now=None):
    return sweep_abandoned_evidence_uploads(now=now or timezone.now() + LATER)


def test_old_unconsumed_unattached_upload_is_deleted_once_with_receipt_and_audit(fake_storage):
    makerspace = space("abandon-basic")
    target = photo(makerspace)

    summary = run()

    assert summary["photos_deleted"] == 1
    assert not EvidencePhoto.objects.filter(pk=target.pk).exists()
    assert fake_storage["deleted"] == [target.object_key, storage.staging_key(target.object_key)]
    receipt = EvidenceAbandonedUploadReceipt.objects.get()
    assert (receipt.source_makerspace_id_snapshot, receipt.evidence_id_snapshot, receipt.object_key) == (
        makerspace.pk, target.pk, target.object_key,
    )
    audits = AuditLog.objects.filter(action="evidence.abandoned_upload_deleted")
    assert audits.count() == 1
    assert audits.get().target_type == "makerspaces.makerspace"
    assert audits.get().meta["evidence_id"] == target.pk
    assert not AuditLog.objects.filter(action="evidence.object_expired").exists()
    assert AuditLog.objects.filter(action="report.retention_fence_satisfied").exists()
    # Idempotent: a second sweep finds nothing new.
    assert run()["photos_deleted"] == 0


@pytest.mark.parametrize("state", [C.LEGACY_UNKNOWN, C.CONSUMED])
def test_legacy_and_consumed_rows_are_never_candidates(fake_storage, state):
    makerspace = space(f"abandon-{state}")
    survivor = photo(makerspace, state=state)
    assert run()["photos_deleted"] == 0
    assert EvidencePhoto.objects.filter(pk=survivor.pk).exists()


def test_global_switch_and_tenant_opt_in_each_prevent_new_cleanup(fake_storage, settings):
    tenant_off = space("abandon-tenant-off", opt_in=False)
    kept = photo(tenant_off)
    assert run()["photos_deleted"] == 0
    settings.EVIDENCE_ABANDONED_UPLOAD_CLEANUP_ENABLED = False
    tenant_on = space("abandon-global-off")
    also_kept = photo(tenant_on)
    assert run()["photos_deleted"] == 0
    assert EvidencePhoto.objects.filter(pk__in=[kept.pk, also_kept.pk]).count() == 2
    assert fake_storage["deleted"] == []
    # Dry-run still reports while disabled, without touching anything.
    summary = sweep_abandoned_evidence_uploads(dry_run=True, now=timezone.now() + LATER)
    assert summary["photos_eligible"] == 1
    assert not EvidenceObjectRetentionState.objects.exists()


def test_age_cutoff_is_strict_and_never_below_presign_ttl(fake_storage, settings):
    makerspace = space("abandon-age", days=7)
    young = photo(makerspace)
    assert run(now=timezone.now() + timedelta(days=6))["photos_deleted"] == 0
    settings.EVIDENCE_URL_TTL_SECONDS = 30 * 86400  # TTL beats the stored policy
    assert run(now=timezone.now() + timedelta(days=20))["photos_deleted"] == 0
    assert EvidencePhoto.objects.filter(pk=young.pk).exists()


@pytest.mark.parametrize("status", ["pending", "promoting"])
def test_active_finalization_is_excluded(fake_storage, status):
    makerspace = space(f"abandon-fin-{status}")
    kept = photo(makerspace)
    EvidenceUploadFinalization.objects.create(evidence=kept, status=status)
    assert run()["photos_deleted"] == 0


def test_finalized_and_expired_uploads_are_cleaned_without_double_quota(
    fake_storage, settings, monkeypatch
):
    settings.STORAGE_PRESIGN_METHOD = "put"
    monkeypatch.setattr("apps.makerspaces.limits.is_self_host", lambda: False)
    makerspace = space("abandon-quota")
    finalized = photo(makerspace, size=40)
    EvidenceUploadFinalization.objects.create(
        evidence=finalized, status="finalized", size_bytes=40, quota_charged=True
    )
    expired = photo(makerspace, size=70)
    EvidenceObjectRetentionState.objects.create(
        evidence=expired, status=S.EXPIRED, object_expired_at=timezone.now(), expired_size_bytes=70
    )
    uncharged = photo(makerspace, size=90)
    EvidenceUploadFinalization.objects.create(
        evidence=uncharged, status="finalized", size_bytes=90, quota_charged=False
    )
    Makerspace.objects.filter(pk=makerspace.pk).update(storage_bytes_used=100)

    summary = run()

    assert summary["photos_deleted"] == 3
    assert summary["quota_released_bytes"] == 40
    makerspace.refresh_from_db()
    assert makerspace.storage_bytes_used == 60
    assert not EvidenceUploadFinalization.objects.exists()
    assert not EvidenceObjectRetentionState.objects.exists()


def test_expiring_claim_is_never_stolen_and_mechanism_a_never_claims_cleaning(
    fake_storage, settings
):
    makerspace = space("abandon-expiring")
    expiring = photo(makerspace)
    EvidenceObjectRetentionState.objects.create(evidence=expiring, status=S.EXPIRING)
    cleaning = photo(makerspace)
    EvidenceObjectRetentionState.objects.create(evidence=cleaning, status=S.CLEANING)
    assert run()["photos_deleted"] == 1  # only the tokenless retryable CLEANING row
    assert EvidencePhoto.objects.filter(pk=expiring.pk).exists()

    settings.EVIDENCE_OBJECT_EXPIRY_ENABLED = True
    other = photo(space("abandon-mech-a", opt_in=False))
    EvidenceObjectRetentionState.objects.create(evidence=other, status=S.CLEANING)
    sweep_evidence_retention(now=timezone.now() + timedelta(days=400))
    assert EvidenceObjectRetentionState.objects.get(evidence=other).status == S.CLEANING


def test_storage_failure_leaves_retryable_cleaning_state_and_no_side_effects(fake_storage):
    makerspace = space("abandon-fail")
    target = photo(makerspace)
    fake_storage["fail"].add(storage.staging_key(target.object_key))

    summary = run()

    assert summary["photos_failed"] == 1
    state = EvidenceObjectRetentionState.objects.get(evidence=target)
    assert (state.status, state.claim_token, state.claimed_at) == (S.CLEANING, None, None)
    assert "boom" in state.last_error
    assert not EvidenceAbandonedUploadReceipt.objects.exists()
    assert not AuditLog.objects.filter(action="evidence.abandoned_upload_deleted").exists()
    fake_storage["fail"].clear()
    assert run()["photos_deleted"] == 1


def test_fresh_competing_claim_is_skipped(fake_storage):
    makerspace = space("abandon-fresh")
    target = photo(makerspace)
    import uuid

    EvidenceObjectRetentionState.objects.create(
        evidence=target, status=S.CLEANING, claim_token=uuid.uuid4(),
        claimed_at=timezone.now() + LATER,
    )
    assert run()["photos_deleted"] == 0


def test_attachment_is_blocked_while_cleaning():
    from apps.evidence.finalization import lock_evidence_for_attachment

    makerspace = space("abandon-attach")
    target = photo(makerspace)
    EvidenceObjectRetentionState.objects.create(evidence=target, status=S.CLEANING)
    with transaction.atomic():
        assert lock_evidence_for_attachment(target.pk) is False


@pytest.mark.parametrize("audit_shape", ["target", "meta-attached", "issued", "triaged"])
def test_consumption_audits_protect_the_photo(fake_storage, audit_shape):
    makerspace = space(f"abandon-audit-{audit_shape}")
    target = photo(makerspace)
    action, kwargs = {
        "target": ("evidence.attached", {"target": target}),
        "meta-attached": ("evidence.attached", {"meta": {"evidence_id": target.pk}}),
        "issued": ("request.issued", {"meta": {"evidence_id": target.pk}}),
        "triaged": ("problem_report.triaged", {"meta": {"evidence_id": target.pk, "outcome": "no_issue"}}),
    }[audit_shape]
    audit.record(None, action, makerspace=makerspace, **kwargs)
    assert run()["photos_deleted"] == 0


def test_cleanup_respects_the_report_fence_and_keeps_history_stable(fake_storage):
    from apps.evidence.reports import build_evidence_compliance

    makerspace = space("abandon-report")
    target = photo(makerspace)
    EvidencePhoto.objects.filter(pk=target.pk)  # created now; bucket is today
    now = timezone.now() + timedelta(days=40)
    from apps.operations.report_rollups import finalize_evidence_rollups

    finalize_evidence_rollups(makerspace, through=now)
    before = build_evidence_compliance(makerspace.pk).records
    assert run(now=now)["photos_deleted"] == 1
    finalize_evidence_rollups(makerspace, through=now)
    assert build_evidence_compliance(makerspace.pk).records == before


def _receipt(makerspace, key="evidence/receipt/k", *, due=None):
    target = photo(makerspace, key=key)
    with transaction.atomic():
        receipt = EvidenceAbandonedUploadReceipt.objects.create(
            source_makerspace_id_snapshot=makerspace.pk,
            evidence_id_snapshot=target.pk,
            object_key=key,
            next_reconcile_at=due or timezone.now(),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [str(target.pk)])
        EvidencePhoto.objects.filter(pk=target.pk).delete()
    return receipt


def test_receipt_is_permanent_at_orm_and_database_boundaries():
    receipt = _receipt(space("abandon-receipt", opt_in=False))
    with pytest.raises(RuntimeError):
        receipt.save()
    with pytest.raises(RuntimeError):
        receipt.delete()
    with pytest.raises(RuntimeError):
        EvidenceAbandonedUploadReceipt.objects.filter(pk=receipt.pk).delete()
    with pytest.raises(RuntimeError):
        EvidenceAbandonedUploadReceipt.objects.filter(pk=receipt.pk).update(last_error="x")
    with pytest.raises(ValueError):
        EvidenceAbandonedUploadReceipt.objects.filter(pk=receipt.pk).reconcile_update(object_key="y")
    for sql in (
        "DELETE FROM evidence_evidenceabandoneduploadreceipt WHERE id=%s",
        "UPDATE evidence_evidenceabandoneduploadreceipt SET object_key='z' WHERE id=%s",
        "UPDATE evidence_evidenceabandoneduploadreceipt SET evidence_id_snapshot=1 WHERE id=%s",
        "UPDATE evidence_evidenceabandoneduploadreceipt SET created_at=now() WHERE id=%s",
    ):
        for guc in ("", "SET LOCAL app.allow_immutable_delete = 'on'"):
            with pytest.raises(Error), transaction.atomic(), connection.cursor() as cursor:
                if guc:
                    cursor.execute(guc)
                cursor.execute(sql, [receipt.pk])
    later = timezone.now() + timedelta(days=1)
    for field, value in (
        ("next_reconcile_at", later), ("last_reconciled_at", later), ("last_error", "e"),
    ):
        assert EvidenceAbandonedUploadReceipt.objects.filter(pk=receipt.pk).reconcile_update(
            **{field: value}
        ) == 1


def test_photo_delete_guard_branches():
    makerspace = space("abandon-guard", opt_in=False)
    target = photo(makerspace, key="evidence/guard/k")

    def attempt(guc_id):
        with pytest.raises(Error), transaction.atomic(), connection.cursor() as cursor:
            if guc_id is not None:
                cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [guc_id])
            cursor.execute("DELETE FROM evidence_evidencephoto WHERE id=%s", [target.pk])

    attempt(None)  # missing GUC
    attempt(str(target.pk))  # no receipt
    with pytest.raises(Error), transaction.atomic():
        EvidenceAbandonedUploadReceipt.objects.create(  # receipt must name the exact row
            source_makerspace_id_snapshot=makerspace.pk + 1,
            evidence_id_snapshot=target.pk, object_key=target.object_key,
            next_reconcile_at=timezone.now(),
        )
    assert EvidencePhoto.objects.filter(pk=target.pk).exists()


def test_reconciliation_runs_while_disabled_and_backs_off_failures(monkeypatch, settings):
    settings.EVIDENCE_ABANDONED_UPLOAD_CLEANUP_ENABLED = False
    settings.EVIDENCE_RETENTION_BATCH_SIZE = 1
    makerspace = space("abandon-reconcile", opt_in=False)
    now = timezone.now()
    first = _receipt(makerspace, "evidence/rec/a", due=now - timedelta(minutes=2))
    second = _receipt(makerspace, "evidence/rec/b", due=now - timedelta(minutes=1))
    deleted = []

    def delete(key):
        if key.endswith("/a"):
            raise storage.StorageUnavailable("down")
        deleted.append(key)
        return "deleted"

    monkeypatch.setattr(storage, "delete_object_strict", delete)

    summary = reconcile_receipts(now=now)
    assert (summary["receipts_failed"], summary["has_more"]) == (1, True)
    first.refresh_from_db()
    assert first.next_reconcile_at == now + FAILURE_BACKOFF and "down" in first.last_error

    summary = reconcile_receipts(now=now)  # the failed head is no longer due
    assert summary["receipts_reconciled"] == 1
    assert deleted == ["evidence/rec/b", "staging/evidence/rec/b"]
    second.refresh_from_db()
    assert second.next_reconcile_at == now + SUCCESS_INTERVAL
    assert second.last_reconciled_at == now
    assert not AuditLog.objects.filter(action="evidence.abandoned_upload_deleted").exists()


def test_reconciliation_survives_purged_source_and_refuses_during_recovery(monkeypatch):
    from apps.backup.models import DeploymentRecoveryState

    makerspace = space("abandon-purged", opt_in=False)
    _receipt(makerspace, "evidence/purged/k")
    deleted = []
    monkeypatch.setattr(storage, "delete_object_strict", lambda key: deleted.append(key) or "deleted")
    DeploymentRecoveryState.objects.filter(pk=1).update(mode=DeploymentRecoveryState.Mode.QUARANTINED)
    assert reconcile_receipts()["recovery_blocked"] is True
    assert deleted == []
    DeploymentRecoveryState.objects.filter(pk=1).update(mode=DeploymentRecoveryState.Mode.NORMAL)
    assert reconcile_receipts()["receipts_reconciled"] == 1


def test_key_reservation_rejects_a_new_photo_on_a_receipt_key():
    makerspace = space("abandon-reserve", opt_in=False)
    _receipt(makerspace, "evidence/reserved/k")
    with pytest.raises(Error), transaction.atomic():
        photo(makerspace, key="evidence/reserved/k")


def test_choose_target_key_regenerates_a_receipt_reserved_key(monkeypatch):
    from apps.tenant_migration import object_storage

    makerspace = space("abandon-choose", opt_in=False)
    _receipt(makerspace, "evidence/choose/k")
    monkeypatch.setattr(object_storage, "object_exists", lambda _kind, _key: False)
    key, regenerated = object_storage.choose_target_key("private", "evidence/choose/k", "job")
    assert regenerated and key != "evidence/choose/k"
    assert object_storage.choose_target_key("public_image", "evidence/choose/k", "job") == (
        "evidence/choose/k", False,
    )


def test_protected_sidecars_block_the_collector_even_with_the_exact_guc():
    makerspace = space("abandon-protect", opt_in=False)
    target = photo(makerspace)
    EvidenceUploadFinalization.objects.create(evidence=target, status="finalized")
    with pytest.raises(ProtectedError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.evidence_abandoned_delete_id = %s", [str(target.pk)])
        EvidencePhoto.objects.filter(pk=target.pk).delete()
    assert EvidenceUploadFinalization.objects.filter(evidence=target).exists()
