from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from django.utils import timezone

from apps.backup import artifact_ledger, artifact_protocol, reconciliation, services
from apps.backup.models import BackupArchive, BackupArtifactLedger, PlatformBackupSettings
from tests.backup.test_promotion_e5 import _prepared


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize(
    ("initial_state", "staging_exists", "final_exists"),
    (
        ("pending", True, False),
        ("staging_verified", True, False),
        ("pending", False, True),
        ("final_verified", False, True),
    ),
)
def test_reconciliation_resumes_every_remote_byte_boundary(
    monkeypatch, tmp_path, initial_state, staging_exists, final_exists
):
    _space, _recipient, _archive, ledger, size, digest = _prepared(tmp_path)
    if initial_state == "staging_verified":
        artifact_ledger.mark_staging_verified(ledger.pk, size, digest)
    elif initial_state == "final_verified":
        artifact_ledger.mark_final_verified(ledger.pk, size, digest)
    promotions = []
    copies = []

    def exists(key):
        if key == ledger.staging_locator:
            return staging_exists
        if key == ledger.final_locator:
            return final_exists
        return False

    monkeypatch.setattr(reconciliation.storage, "object_exists", exists)
    monkeypatch.setattr(
        reconciliation.storage, "stream_verify", lambda *_args, **_kwargs: (size, digest)
    )
    monkeypatch.setattr(
        reconciliation.storage, "create_final_from_staging",
        lambda staging, final: copies.append((staging, final)),
    )
    monkeypatch.setattr(reconciliation.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        reconciliation, "promote_verified_artifact",
        lambda artifact_id: promotions.append(artifact_id),
    )

    reconciliation._reconcile_pending(ledger.pk)

    ledger.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.FINAL_VERIFIED
    assert promotions == [ledger.pk]
    assert bool(copies) is (not final_exists)


def test_pending_without_remote_bytes_is_failed_and_tombstoned(monkeypatch, tmp_path):
    _space, _recipient, archive, ledger, _size, _digest = _prepared(tmp_path)
    monkeypatch.setattr(reconciliation.storage, "object_exists", lambda _key: False)
    monkeypatch.setattr(reconciliation.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        reconciliation.storage, "delete_archive_prefix", lambda _prefix: True
    )

    assert reconciliation.reconcile_artifact_uploads() == 1

    ledger.refresh_from_db()
    archive.refresh_from_db()
    assert ledger.state == BackupArtifactLedger.State.FAILED
    assert archive.status == BackupArchive.Status.FAILED


def test_available_artifact_only_retries_staging_cleanup(monkeypatch, tmp_path):
    _space, _recipient, _archive, ledger, size, digest = _prepared(tmp_path)
    artifact_ledger.mark_final_verified(ledger.pk, size, digest)
    BackupArtifactLedger.objects.filter(pk=ledger.pk).update(
        state=BackupArtifactLedger.State.AVAILABLE,
        cleanup_pending=True,
        promoted_at=timezone.now(),
    )
    deleted = []
    monkeypatch.setattr(
        reconciliation.storage, "delete_archive", lambda key: deleted.append(key) or True
    )

    assert reconciliation.reconcile_artifact_uploads() == 0

    ledger.refresh_from_db()
    assert deleted == [ledger.staging_locator]
    assert ledger.cleanup_pending is False
    assert ledger.state == BackupArtifactLedger.State.AVAILABLE


def test_final_readback_precedes_any_promotion_lock(monkeypatch):
    events = []
    ledger = SimpleNamespace(
        artifact_id=uuid.uuid4(),
        staging_locator="backup-archives/staging/a.tar.age",
        final_locator="backup-archives/deployment/a.tar.age",
        expected_size_bytes=9,
        outer_sha256="a" * 64,
    )
    build = SimpleNamespace(encrypted="/tmp/not-opened")
    monkeypatch.setattr(
        artifact_protocol, "persist_pending", lambda *_args: events.append("persist") or ledger
    )
    monkeypatch.setattr(
        artifact_protocol.storage, "upload_staging", lambda *_args: events.append("upload")
    )

    def verify(key, **_kwargs):
        events.append("verify-final" if key == ledger.final_locator else "verify-staging")
        return 9, "a" * 64

    monkeypatch.setattr(artifact_protocol.storage, "stream_verify", verify)
    monkeypatch.setattr(
        artifact_protocol.storage, "create_final_from_staging",
        lambda *_args: events.append("create-final"),
    )
    monkeypatch.setattr(artifact_protocol.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        artifact_protocol, "mark_staging_verified", lambda *_args: events.append("mark-staging")
    )
    monkeypatch.setattr(
        artifact_protocol, "mark_final_verified", lambda *_args: events.append("mark-final")
    )
    monkeypatch.setattr(
        artifact_protocol, "promote_verified_artifact",
        lambda _artifact_id: events.append("promotion-locks") or "available",
    )
    monkeypatch.setattr(
        artifact_protocol, "mark_cleanup_complete", lambda _artifact_id: events.append("clean")
    )

    artifact_protocol.upload_verify_and_promote(SimpleNamespace(), build, 9)

    assert events.index("verify-final") < events.index("promotion-locks")


def test_failed_new_run_preserves_previous_success(monkeypatch, tmp_path):
    succeeded_at = timezone.now() - timedelta(hours=1)
    previous = BackupArchive.objects.create(
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=BackupArchive.Status.AVAILABLE,
        object_key=f"backup-archives/deployment/{uuid.uuid4()}.tar.age",
        expires_at=timezone.now() + timedelta(days=1),
    )
    settings_row = PlatformBackupSettings.load()
    settings_row.last_success_at = succeeded_at
    settings_row.save(update_fields=("last_success_at", "updated_at"))
    _space, _recipient, failed, _ledger, _size, _digest = _prepared(tmp_path)
    monkeypatch.setattr(services.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        services.storage, "delete_archive_prefix", lambda _prefix: True
    )

    services._fail_archive(failed, "injected new-run failure")

    previous.refresh_from_db()
    failed.refresh_from_db()
    settings_row.refresh_from_db()
    assert previous.status == BackupArchive.Status.AVAILABLE
    assert failed.status == BackupArchive.Status.FAILED
    assert settings_row.last_success_at == succeeded_at
