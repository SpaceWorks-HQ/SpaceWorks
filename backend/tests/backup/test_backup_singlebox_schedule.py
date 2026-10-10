"""Exercise the backup jobs reached by the single-box cron, without a host restore."""

from datetime import timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.backup import tasks
from apps.backup.models import BackupRun
from apps.operations.management.commands import run_scheduled_tasks as scheduler
from apps.operations.models import PeriodicTaskRun

pytestmark = pytest.mark.django_db


def test_singlebox_cron_reaches_due_backup_reconcile_offsite_and_retention_jobs(monkeypatch):
    names = {
        "scheduled-deployment-backup", "reconcile-backup-artifacts", "push-offsite-backups",
        "purge-expired-backup-archives", "cleanup-expired-restore-rollbacks",
    }
    calls = []
    monkeypatch.setattr(scheduler, "SCHEDULED_TASKS", tuple(
        row for row in scheduler.SCHEDULED_TASKS if row[0] in names
    ))
    monkeypatch.setattr(tasks, "schedule_deployment_backup",
                        lambda: calls.append("build") or SimpleNamespace(status=BackupRun.Status.COMPLETE))
    monkeypatch.setattr(tasks, "dispatch_offsite_push", lambda: calls.append("dispatch") or True)
    monkeypatch.setattr(tasks, "reconcile_artifact_uploads", lambda: calls.append("reconcile") or 0)
    monkeypatch.setattr(tasks, "purge_expired_archives", lambda: calls.append("prune") or 0)
    monkeypatch.setattr(tasks, "cleanup_expired_rollback_objects", lambda: calls.append("rollback-cleanup") or 0)
    for module, name in (
        ("offsite_push", "enqueue_offsite_uploads"), ("offsite_push", "push_due_uploads"),
        ("offsite_retention", "prune_offsite_copies"), ("offsite_reverify", "reverify_offsite_copies"),
    ):
        monkeypatch.setattr(f"apps.backup.{module}.{name}",
                            lambda name=name: calls.append(name) or 0)
    for name in names:
        PeriodicTaskRun.objects.create(name=name, last_run_at=timezone.now() - timedelta(days=2))
    output = StringIO()

    call_command("run_scheduled_tasks", "--due-only", stdout=output)

    assert set(calls) == {
        "build", "dispatch", "reconcile", "prune", "rollback-cleanup",
        "enqueue_offsite_uploads", "push_due_uploads", "prune_offsite_copies", "reverify_offsite_copies",
    }
    assert all(f"ran {name}" in output.getvalue() for name in names)
    assert not PeriodicTaskRun.objects.exclude(last_error="").exists()
    previous = list(calls)
    call_command("run_scheduled_tasks", "--due-only", stdout=StringIO())
    assert calls == previous


def test_singlebox_image_has_age_and_runs_the_backup_scheduler_through_cron_admission():
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "Dockerfile.allinone").read_text()
    launcher = (root / "docker/allinone/run.sh").read_text()
    assert "gnupg age nginx" in dockerfile
    assert "launch cron $ENTRYPOINT --role cron" in launcher
    assert "python manage.py run_scheduled_tasks --due-only" in launcher
