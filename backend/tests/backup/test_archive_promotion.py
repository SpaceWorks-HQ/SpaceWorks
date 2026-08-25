from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.backup import services
from apps.backup import services_archives
from apps.backup.models import BackupArchive, PlatformBackupSettings
from apps.backup.operation_lock import OperationLockUnavailable


pytestmark = pytest.mark.django_db


def _archive(status, holder=None):
    archive_id = uuid.uuid4()
    return BackupArchive.objects.create(
        id=archive_id,
        scope=BackupArchive.Scope.DEPLOYMENT,
        status=status,
        build_holder=holder,
        object_key=f"backup-archives/deployment/{archive_id}.tar.age",
        staging_object_key=(
            f"backup-archives/staging/{archive_id}/{holder}.tar.age"
            if holder else None
        ),
    )


def test_losing_terminal_cas_has_no_object_settings_or_audit_side_effect(monkeypatch):
    owner = uuid.uuid4()
    loser = uuid.uuid4()
    running = _archive(BackupArchive.Status.RUNNING, owner)
    promoting = _archive(BackupArchive.Status.PROMOTING, owner)
    deleted = []
    monkeypatch.setattr(
        services_archives.storage, "delete_archive", lambda key: deleted.append(key)
    )
    monkeypatch.setattr(
        services_archives.storage,
        "delete_archive_prefix",
        lambda key: deleted.append(key),
    )

    assert services._fail_archive(
        running.pk,
        loser,
        "late acknowledgement",
        expected_status=BackupArchive.Status.RUNNING,
    ) is False
    assert services._complete_archive(
        promoting.pk, loser, {"winner": False}, 99, "b" * 64
    ) is False

    running.refresh_from_db()
    promoting.refresh_from_db()
    assert running.status == BackupArchive.Status.RUNNING
    assert promoting.status == BackupArchive.Status.PROMOTING
    assert promoting.manifest == {}
    assert deleted == []
    assert PlatformBackupSettings.objects.count() == 0


def test_dispatch_failure_cas_is_holderless_and_deletes_no_object(monkeypatch):
    archive = _archive(BackupArchive.Status.PENDING)
    deleted = []
    monkeypatch.setattr(
        services_archives.storage, "delete_archive", lambda key: deleted.append(key)
    )
    monkeypatch.setattr(
        services_archives.storage,
        "delete_archive_prefix",
        lambda key: deleted.append(key),
    )

    assert services.fail_archive_dispatch(archive, RuntimeError("broker down")) is True

    archive.refresh_from_db()
    assert archive.status == BackupArchive.Status.FAILED
    assert deleted == []


def test_stale_promotion_cas_precedes_final_and_prefix_deletion(monkeypatch):
    after_claim = _archive(BackupArchive.Status.PROMOTING, uuid.uuid4())
    after_copy = _archive(BackupArchive.Status.PROMOTING, uuid.uuid4())
    events = []
    objects = {
        after_claim.staging_object_key,
        after_copy.staging_object_key,
        after_copy.object_key,
    }

    def delete_final(key):
        archive = BackupArchive.objects.get(object_key=key)
        assert archive.status == BackupArchive.Status.FAILED
        objects.discard(key)
        events.append(("final", archive.pk))
        return True

    def delete_prefix(prefix):
        archive_id = uuid.UUID(prefix.rstrip("/").rsplit("/", 1)[-1])
        assert BackupArchive.objects.get(pk=archive_id).status == BackupArchive.Status.FAILED
        objects.difference_update(key for key in tuple(objects) if key.startswith(prefix))
        events.append(("prefix", archive_id))
        return True

    monkeypatch.setattr(services_archives.storage, "delete_archive", delete_final)
    monkeypatch.setattr(services_archives.storage, "delete_archive_prefix", delete_prefix)

    assert services.sweep_stale_promotions() == 2
    assert {event[1] for event in events} == {after_claim.pk, after_copy.pk}
    assert len(events) == 4
    assert objects == set()


def test_duplicate_that_loses_operation_lock_cannot_fail_owner_archive(monkeypatch):
    owner = uuid.uuid4()
    archive = _archive(BackupArchive.Status.RUNNING, owner)
    deleted = []

    @contextmanager
    def unavailable_lock():
        raise OperationLockUnavailable("busy")
        yield

    monkeypatch.setattr(
        services_archives, "deployment_operation_lock", unavailable_lock
    )
    monkeypatch.setattr(
        services_archives.storage, "delete_archive", lambda key: deleted.append(key)
    )

    result = services.run_archive(archive.pk)

    archive.refresh_from_db()
    assert result.status == BackupArchive.Status.RUNNING
    assert archive.build_holder == owner
    assert deleted == []


def test_available_transition_sweeps_winner_loser_and_crashed_staging(monkeypatch):
    holder = uuid.uuid4()
    archive = _archive(BackupArchive.Status.PROMOTING, holder)
    prefix = f"backup-archives/staging/{archive.pk}/"
    staged = {
        f"{prefix}{holder}.tar.age",
        f"{prefix}{uuid.uuid4()}.tar.age",
        f"{prefix}{uuid.uuid4()}.tar.age",
    }

    def delete_prefix(received):
        assert received == prefix
        staged.difference_update(key for key in tuple(staged) if key.startswith(received))
        return True

    monkeypatch.setattr(services_archives.storage, "delete_archive_prefix", delete_prefix)
    assert services._complete_archive(
        archive.pk, holder, {"ok": True}, 12, "a" * 64
    ) is True

    archive.refresh_from_db()
    assert archive.status == BackupArchive.Status.AVAILABLE
    assert archive.expires_at > timezone.now() + timedelta(days=29)
    assert staged == set()


def test_standalone_archive_path_sweeps_manual_promotion_orphan(monkeypatch):
    orphan = _archive(BackupArchive.Status.PROMOTING, uuid.uuid4())
    lock_events = []

    @contextmanager
    def lock():
        lock_events.append("acquired")
        yield
        lock_events.append("released")

    monkeypatch.setattr(services_archives, "deployment_operation_lock", lock)
    monkeypatch.setattr(services_archives.storage, "delete_archive", lambda _key: True)
    monkeypatch.setattr(
        services_archives.storage, "delete_archive_prefix", lambda _prefix: True
    )
    monkeypatch.setattr(
        services_archives,
        "_run_archive_locked",
        lambda archive_id: BackupArchive.objects.get(pk=archive_id),
    )

    result = services.run_archive(orphan.pk)

    assert result.status == BackupArchive.Status.FAILED
    assert lock_events == ["acquired", "released"]
