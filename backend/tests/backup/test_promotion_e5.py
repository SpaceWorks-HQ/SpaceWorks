from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.audit import services as audit_services
from apps.audit.models import AuditLog
from apps.backup import artifact_ledger, outer_manifest, promotion, reconciliation
from apps.backup.models import (
    B1ActivationState,
    BackupArchive,
    BackupArtifactLedger,
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
    PlatformBackupSettings,
)
from apps.backup.recipients import fingerprint_for
from apps.backup.user_closure import user_closure_digest
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db(transaction=True)


def _prepared(tmp_path):
    space = Makerspace.objects.create(
        name="E5 sovereign", slug=f"e5-{uuid.uuid4().hex}",
        superadmin_access_enabled=False,
    )
    recipient_value = f"age1e5{uuid.uuid4().hex}"
    recipient = MakerspaceArchiveRecipient.objects.create(
        makerspace=space,
        public_recipient=recipient_value,
        fingerprint=fingerprint_for(recipient_value),
        label="E5 tenant key",
        verified_at=timezone.now(),
    )
    MakerspaceArchiveCustodyState.objects.create(
        makerspace=space,
        state=MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
    )
    archive = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.RUNNING,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    capture_id = uuid.uuid4()
    slice_id = outer_manifest.component_id(capture_id, "slice", space.pk)
    capture = SimpleNamespace(
        capture_id=capture_id,
        frozen_population_ids=(space.pk,),
        frozen_slices=(SimpleNamespace(
            makerspace_id=space.pk,
            custody_state=MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
        ),),
        expected_main_ledger={"catalog": "verified"},
        user_closure_digest=user_closure_digest(
            (("stubbed", "1", "sovereign-global-user-reference"),)
        ),
        slice_entries=[{
            "component_id": slice_id,
            "makerspace_id": space.pk,
            "path": f"slices/{slice_id}.tar.age",
            "size_bytes": 11,
            "ciphertext_sha256": "b" * 64,
            "recipient_fingerprints": [recipient.fingerprint],
            "object_ledger_count": 0,
            "object_ledger_digest": "c" * 64,
            "content_ledger_count": 3,
            "content_ledger_digest": "f" * 64,
        }],
    )
    Path(tmp_path, "database.dump").write_bytes(b"main")
    detailed = {
        "format": "spaceworks-phase5a-v3",
        "snapshot_at": timezone.now().isoformat(),
        "build": {"git_sha": "e5"},
        "recipient_fingerprints": ["d" * 64],
        "storage": {"objects": []},
        "contents": [],
    }
    manifest = outer_manifest.build_outer_manifest(
        archive=archive, capture=capture, detailed_manifest=detailed, root=tmp_path
    )
    size, digest = 101, "e" * 64
    build = SimpleNamespace(
        manifest=manifest,
        promotion_snapshot={
            "predecessor_artifact_id": None,
            "predecessor_success_at": None,
            "retained": [{
                "makerspace_id": space.pk,
                "superadmin_access_enabled": False,
                "activation_state": B1ActivationState.State.OFF_PENDING,
                "custody_state": MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT,
                "recipients": [{"pk": recipient.pk, "fingerprint": recipient.fingerprint}],
            }],
        },
        archive_sha256=digest,
    )
    ledger = artifact_ledger.persist_pending(archive, build, size)
    return space, recipient, archive, ledger, size, digest


def _final_verified(tmp_path):
    values = _prepared(tmp_path)
    artifact_ledger.mark_final_verified(values[3].pk, values[4], values[5])
    return values


def test_promotion_commits_activation_availability_audit_and_success_together(tmp_path):
    space, _recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)

    promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    ledger.refresh_from_db()
    activation = B1ActivationState.objects.get(makerspace=space)
    completed = AuditLog.objects.get(action="backup.archive_completed", target_id=str(archive.pk))
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert ledger.state == BackupArtifactLedger.State.AVAILABLE
    assert activation.state == B1ActivationState.State.OFF_EFFECTIVE
    assert completed.meta["user_closure_digest"] == archive.manifest["user_closure_digest"]
    assert PlatformBackupSettings.load().last_success_at == archive.completed_at


def test_promotion_rolls_back_every_success_write_when_completion_audit_fails(
    monkeypatch, tmp_path
):
    space, _recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)
    real_record = audit_services.record

    def fail_completed(actor, action, **kwargs):
        if action == "backup.archive_completed":
            raise RuntimeError("injected audit failure")
        return real_record(actor, action, **kwargs)

    monkeypatch.setattr(promotion.audit, "record", fail_completed)
    with pytest.raises(RuntimeError, match="audit failure"):
        promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert archive.status == BackupArchive.Status.RUNNING
    assert ledger.state == BackupArtifactLedger.State.FINAL_VERIFIED
    assert B1ActivationState.objects.get(makerspace=space).state == "off_pending"
    assert not AuditLog.objects.filter(action="backup.archive_exclusion_activated").exists()
    assert PlatformBackupSettings.load().last_success_at is None


@pytest.mark.parametrize("field", ("revoked_at", "compromised_at"))
def test_post_capture_revocation_or_compromise_aborts_promotion(tmp_path, field):
    space, recipient, archive, ledger, _size, _digest = _final_verified(tmp_path)
    setattr(recipient, field, timezone.now())
    recipient.save(update_fields=(field,))

    with pytest.raises(artifact_ledger.ArtifactLedgerMismatch, match="recipient set"):
        promotion.promote_verified_artifact(ledger.pk)

    archive.refresh_from_db()
    ledger.refresh_from_db()
    assert archive.status == BackupArchive.Status.RUNNING
    assert ledger.state == BackupArtifactLedger.State.FINAL_VERIFIED
    assert B1ActivationState.objects.get(makerspace=space).state == "off_pending"


def test_pending_final_reconciliation_uses_the_shared_promotion_primitive(
    monkeypatch, tmp_path
):
    _space, _recipient, _archive, ledger, size, digest = _prepared(tmp_path)
    calls = []
    monkeypatch.setattr(
        reconciliation.storage, "object_exists",
        lambda key: key == ledger.final_locator,
    )
    monkeypatch.setattr(
        reconciliation.storage, "stream_verify", lambda *_args, **_kwargs: (size, digest)
    )
    monkeypatch.setattr(reconciliation.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        reconciliation, "promote_verified_artifact", lambda artifact_id: calls.append(artifact_id)
    )

    reconciliation._reconcile_pending(ledger.pk)

    ledger.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.FINAL_VERIFIED
    assert calls == [ledger.pk]


def test_repeated_pending_persistence_is_idempotent(tmp_path):
    _space, _recipient, archive, first, size, _digest = _prepared(tmp_path)
    build = SimpleNamespace(
        manifest=first.outer_manifest,
        promotion_snapshot=first.frozen_promotion_snapshot,
        archive_sha256=first.outer_sha256,
    )

    second = artifact_ledger.persist_pending(archive, build, size)

    assert second.pk == first.pk
    assert second.components.count() == 2
    assert sum(item.recipient_associations.count() for item in second.components.all()) == 2


def test_runner_and_reconciler_share_the_declared_promotion_lock_order():
    assert reconciliation.promote_verified_artifact is promotion.promote_verified_artifact
    assert promotion.PROMOTION_LOCK_ORDER == (
        "makerspaces", "recipients", "activation", "artifacts", "components",
        "recipient_associations", "archive", "platform_settings",
    )
