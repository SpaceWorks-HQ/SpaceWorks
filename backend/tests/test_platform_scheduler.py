from io import StringIO

import pytest
from celery.signals import task_postrun
from django.core.cache import cache
from django.core.management import call_command

from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.operations.models_scheduling import PeriodicTaskRun
from apps.operations.scheduler_telemetry import _task_names, record_periodic_completion
from apps.operations.tasks_platform import PROBLEM_RUN_CACHE_KEY, run_platform_problem_checks_task
from apps.tenant_migration.gate_policy import TASK_EXEMPTIONS
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db
TASK = "apps.operations.tasks_platform.run_platform_problem_checks_task"


def test_checker_is_registered_with_same_cadence_and_explicit_gate_policy(settings):
    assert ("platform-problem-checks", TASK, 15) in SCHEDULED_TASKS
    entry = settings.CELERY_BEAT_SCHEDULE["platform-problem-checks"]
    assert entry["task"] == TASK
    assert entry["schedule"]._orig_minute == "*/15"
    assert TASK in TASK_EXEMPTIONS
    assert run_platform_problem_checks_task.name == TASK


def test_scheduled_check_runs_and_caches_only_deployment_summary():
    make_space("scheduled-check-tenant")
    cache.delete(PROBLEM_RUN_CACHE_KEY)
    call_command("run_scheduled_tasks", "--task", "platform-problem-checks", stdout=StringIO())
    row = PeriodicTaskRun.objects.get(name="platform-problem-checks")
    assert row.last_error == ""
    summary = cache.get(PROBLEM_RUN_CACHE_KEY)
    assert set(summary) == {"checked_at", "status"}
    assert "scheduled-check-tenant" not in str(summary)
    cache.delete(PROBLEM_RUN_CACHE_KEY)


def test_celery_completion_and_failure_update_cron_journal():
    _task_names.cache_clear()
    record_periodic_completion(TASK, "FAILURE")
    assert PeriodicTaskRun.objects.get(name="platform-problem-checks").last_error == "TaskFailure"
    record_periodic_completion(TASK, "SUCCESS")
    assert PeriodicTaskRun.objects.get(name="platform-problem-checks").last_error == ""
    _task_names.cache_clear()


def test_celery_signal_is_wired_and_does_not_store_exception_text():
    import config.celery_signals  # noqa: F401 - connect real signal handlers
    task_postrun.send(sender=run_platform_problem_checks_task,
                      task=run_platform_problem_checks_task, state="FAILURE",
                      retval=RuntimeError("provider-secret"))
    row = PeriodicTaskRun.objects.get(name="platform-problem-checks")
    assert row.last_error == "TaskFailure"


def test_reexported_celery_task_resolves_to_same_cron_name():
    from apps.backup.tasks_offsite import push_offsite_backups_task
    record_periodic_completion(push_offsite_backups_task.name, "SUCCESS")
    assert PeriodicTaskRun.objects.filter(name="push-offsite-backups").exists()


def test_unknown_and_nonterminal_tasks_do_not_write_journal():
    record_periodic_completion("unrelated.task", "SUCCESS")
    record_periodic_completion(TASK, "RETRY")
    assert not PeriodicTaskRun.objects.exists()


def test_telemetry_database_failure_does_not_crash_worker(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(PeriodicTaskRun.objects, "update_or_create", fail)
    record_periodic_completion(TASK, "SUCCESS")


def test_one_unimportable_task_does_not_disable_all_completion_telemetry(monkeypatch, caplog):
    from apps.operations.management.commands import run_scheduled_tasks as runner

    import_task = runner._import_task

    def unavailable(path):
        if path == "apps.hardware_requests.tasks.send_return_reminders_task":
            raise ImportError("provider-secret")
        return import_task(path)

    monkeypatch.setattr(runner, "_import_task", unavailable)
    _task_names.cache_clear()
    try:
        record_periodic_completion(TASK, "SUCCESS")
        assert PeriodicTaskRun.objects.get(name="platform-problem-checks").last_error == ""
        assert "scheduler_task_unavailable" in caplog.text
        assert "provider-secret" not in caplog.text
    finally:
        _task_names.cache_clear()
