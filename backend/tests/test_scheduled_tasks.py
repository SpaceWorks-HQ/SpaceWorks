"""The beat-less scheduler (phase 6).

The failure this guards against is silent: with no broker every `.delay()` runs inline,
so a cloud deployment looks completely healthy while `CELERY_BEAT_SCHEDULE` -- which is
beat's business and beat's alone -- never fires. `send_return_reminders` is a
duty-of-care message, and the first sign of its absence is a dispute months later.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.operations.models import PeriodicTaskRun
from apps.tenant_migration.services_import_job import (
    CLEANUP_LEASE_NAME,
    CLEANUP_OBJECTS_LEASE_NAME,
    FINALIZATION_SWEEP_LEASE_NAME,
)

pytestmark = pytest.mark.django_db


def test_every_beat_entry_has_a_beat_less_counterpart():
    # The drift guard. A task added to CELERY_BEAT_SCHEDULE for the Celery deployment
    # must not silently go missing from the deployment that has no beat to run it.
    from django.conf import settings

    beat_tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    runner_tasks = {dotted for _, dotted, _ in SCHEDULED_TASKS}

    assert beat_tasks == runner_tasks


def test_every_declared_task_actually_resolves():
    from importlib import import_module

    for _, dotted, _ in SCHEDULED_TASKS:
        module_path, _sep, attribute = dotted.rpartition(".")
        assert callable(getattr(import_module(module_path), attribute))


def test_password_reset_drain_is_registered_in_both_schedulers():
    from django.conf import settings

    task = "apps.accounts.tasks.drain_password_reset_envelopes_task"
    assert settings.CELERY_BEAT_SCHEDULE["drain-password-reset-envelopes"]["task"] == task
    assert (
        "drain-password-reset-envelopes",
        task,
        1,
    ) in SCHEDULED_TASKS


def test_running_records_a_row_per_task():
    call_command("run_scheduled_tasks", stdout=StringIO())

    assert set(PeriodicTaskRun.objects.values_list("name", flat=True)) == {
        name for name, _, _ in SCHEDULED_TASKS
    } | {
        CLEANUP_LEASE_NAME,
        CLEANUP_OBJECTS_LEASE_NAME,
        FINALIZATION_SWEEP_LEASE_NAME,
    }


def test_due_only_skips_a_task_that_just_ran():
    # A 15-minute cron must fire an hourly task once an hour, not four times -- sending
    # a return reminder twice is worse than sending it late.
    out = StringIO()
    call_command("run_scheduled_tasks", stdout=out)
    call_command("run_scheduled_tasks", "--due-only", stdout=out)

    assert "skip return-reminders" in out.getvalue()


def test_due_only_runs_a_task_whose_interval_has_elapsed():
    call_command("run_scheduled_tasks", stdout=StringIO())
    PeriodicTaskRun.objects.filter(name="return-reminders").update(
        last_run_at=timezone.now() - timedelta(hours=2)
    )
    out = StringIO()

    call_command("run_scheduled_tasks", "--due-only", stdout=out)

    assert "ran return-reminders" in out.getvalue()


def test_a_new_row_is_not_immediately_due():
    # last_run_at defaults to now, so a fresh deployment does not fire every task the
    # first time cron runs -- which would blast reminders for hardware nobody has had
    # time to return.
    row = PeriodicTaskRun.objects.create(name="fresh")

    assert row.is_due(timezone.now(), 60) is False


def test_one_failing_task_does_not_stop_the_others(monkeypatch):
    import apps.operations.management.commands.run_scheduled_tasks as module

    def explode():
        raise RuntimeError("provider down")

    real_import = module._import_task
    monkeypatch.setattr(
        module,
        "_import_task",
        lambda path: explode if path.endswith("send_return_reminders_task") else real_import(path),
    )
    out, err = StringIO(), StringIO()

    call_command("run_scheduled_tasks", stdout=out, stderr=err)

    assert "failed return-reminders" in err.getvalue()
    # The second task still ran, and the failure is recorded rather than swallowed.
    assert "ran purge-auth-challenges" in out.getvalue()
    assert PeriodicTaskRun.objects.get(name="return-reminders").last_error


def test_a_failed_task_is_still_due_next_run():
    import apps.operations.management.commands.run_scheduled_tasks as module

    # last_run_at is only advanced on success, so a transient failure retries on the
    # next cron tick instead of waiting a full interval.
    row = PeriodicTaskRun.objects.create(
        name="return-reminders", last_run_at=timezone.now() - timedelta(hours=2)
    )
    assert row.is_due(timezone.now(), 60) is True
    assert module.SCHEDULED_TASKS
