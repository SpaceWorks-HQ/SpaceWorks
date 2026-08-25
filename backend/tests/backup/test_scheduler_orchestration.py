from contextlib import contextmanager
from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from apps.backup import services_runs, tasks
from apps.backup.models import (
    BackupArchive,
    BackupLease,
    BackupRun,
    PlatformBackupSettings,
)
from apps.makerspaces.models import Makerspace


pytestmark = pytest.mark.django_db


def _space(label, *, enabled=False):
    return Makerspace.objects.create(
        name=label,
        slug=f"{label}-{uuid.uuid4().hex[:8]}",
        superadmin_access_enabled=enabled,
    )


def _enable_scheduler():
    row = PlatformBackupSettings.load()
    row.automatic_backups_enabled = True
    row.save(update_fields=("automatic_backups_enabled", "updated_at"))


def _install_fast_archive_builder(monkeypatch, events):
    def build(archive_id, **_kwargs):
        archive = BackupArchive.objects.select_related("backup_run").get(pk=archive_id)
        assert not events or events[-1][0] != "pause"
        events.append(("pause", archive.pk))
        completed_at = timezone.now()
        covered = (
            [archive.makerspace_id]
            if archive.scope == BackupArchive.Scope.MAKERSPACE
            else [
                int(key)
                for key, enabled in archive.backup_run.flag_snapshot.items()
                if enabled
            ]
        )
        BackupArchive.objects.filter(pk=archive.pk).update(
            status=BackupArchive.Status.AVAILABLE,
            manifest={
                "backup_run_id": str(archive.backup_run_id),
                "covered_makerspace_ids": covered,
            },
            archive_sha256="a" * 64,
            completed_at=completed_at,
            expires_at=completed_at + timedelta(days=1),
        )
        events.append(("resume", archive.pk))
        return BackupArchive.objects.get(pk=archive.pk)

    monkeypatch.setattr(services_runs, "_run_archive_locked", build)
    monkeypatch.setattr(services_runs, "_claim_lease", lambda _holder: True)
    monkeypatch.setattr(services_runs, "_renew_lease", lambda _holder: True)


def test_three_switch_off_tenants_share_one_lock_and_build_serially(monkeypatch):
    spaces = [_space(f"off-{index}") for index in range(3)]
    _enable_scheduler()
    archive_events = []
    lock_events = []

    @contextmanager
    def lock():
        lock_events.append("acquired")
        yield
        lock_events.append(BackupRun.objects.latest("started_at").status)

    _install_fast_archive_builder(monkeypatch, archive_events)
    monkeypatch.setattr(services_runs, "deployment_operation_lock", lock)
    monkeypatch.setattr(
        services_runs,
        "_release_lease",
        lambda holder: lock_events.append(
            ("lease_released", BackupRun.objects.get(holder=holder).status)
        ),
    )

    run = services_runs.schedule_deployment_backup()

    assert run.status == BackupRun.Status.COMPLETE
    assert lock_events == [
        "acquired",
        ("lease_released", BackupRun.Status.COMPLETE),
        BackupRun.Status.COMPLETE,
    ]
    tenants = BackupArchive.objects.filter(scope=BackupArchive.Scope.MAKERSPACE)
    assert tenants.count() == 3
    assert set(tenants.values_list("makerspace_id", flat=True)) == {
        space.pk for space in spaces
    }
    assert set(tenants.values_list("superadmin_access_at_decision", flat=True)) == {False}
    assert len(archive_events) == 8
    assert all(
        archive_events[index][0] == ("pause" if index % 2 == 0 else "resume")
        for index in range(8)
    )


def test_stale_run_is_failed_before_the_replacement_opens(monkeypatch):
    space = _space("stale", enabled=True)
    stale = BackupRun.objects.create(
        cohort_at=timezone.now(),
        flag_snapshot={str(space.pk): True},
        holder=uuid.uuid4(),
    )
    BackupLease.objects.create(
        name="deployment-backup",
        holder=stale.holder,
        leased_until=timezone.now() + timedelta(hours=1),
    )
    _enable_scheduler()

    @contextmanager
    def lock():
        yield

    monkeypatch.setattr(services_runs, "deployment_operation_lock", lock)
    monkeypatch.setattr(services_runs, "_start_run", lambda _run: None)
    monkeypatch.setattr(services_runs, "_build_run_archives", lambda _run: None)

    replacement = services_runs.schedule_deployment_backup()

    stale.refresh_from_db()
    assert stale.status == BackupRun.Status.FAILED
    assert replacement.pk != stale.pk
    assert BackupRun.objects.count() == 2


def test_disabled_scheduler_still_sweeps_promotions_under_lock(monkeypatch):
    events = []

    @contextmanager
    def lock():
        events.append("lock")
        yield

    monkeypatch.setattr(services_runs, "deployment_operation_lock", lock)
    monkeypatch.setattr(
        services_runs,
        "sweep_stale_promotions",
        lambda: events.append("sweep"),
    )
    monkeypatch.setattr(services_runs, "_fail_stale_runs", lambda: None)

    assert services_runs.schedule_deployment_backup() is None
    assert events == ["lock", "sweep"]


@pytest.mark.parametrize(
    ("status", "expected"),
    [(BackupRun.Status.COMPLETE, True), (BackupRun.Status.FAILED, False)],
)
def test_scheduled_task_reports_only_complete_runs(monkeypatch, status, expected):
    run = type("Run", (), {"status": status})()
    monkeypatch.setattr(tasks, "schedule_deployment_backup", lambda: run)
    assert tasks.scheduled_deployment_backup_task.run() is expected
