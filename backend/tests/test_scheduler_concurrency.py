"""A due-only scheduler claim prevents duplicate runs while work happens outside locks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Event

import pytest
from django.core.management import call_command
from django.db import close_old_connections
from django.utils import timezone

from apps.operations.models import PeriodicTaskRun

pytestmark = pytest.mark.django_db(transaction=True)


def test_second_runner_skips_an_in_flight_claim(monkeypatch):
    import apps.operations.management.commands.run_scheduled_tasks as module

    PeriodicTaskRun.objects.create(name="return-reminders", last_run_at=timezone.now() - timedelta(hours=2))
    started, release = Event(), Event()
    calls = []

    def task():
        calls.append(True)
        started.set()
        assert release.wait(10), "second scheduler did not finish its due check"

    monkeypatch.setattr(module, "_import_task", lambda path: task)

    def run():
        close_old_connections()
        try:
            output = StringIO()
            call_command("run_scheduled_tasks", "--task", "return-reminders", "--due-only", stdout=output)
            return output.getvalue()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        try:
            assert started.wait(10)
            second = pool.submit(run)
            assert "skip return-reminders" in second.result(timeout=10)
        finally:
            release.set()
        assert "ran return-reminders" in first.result(timeout=10)
    assert calls == [True]


def test_scheduler_failure_keeps_secrets_out_of_the_control_row_and_stderr(monkeypatch):
    import apps.operations.management.commands.run_scheduled_tasks as module

    def task():
        raise RuntimeError("provider-credential-secret")

    monkeypatch.setattr(module, "_import_task", lambda path: task)
    error = StringIO()
    call_command("run_scheduled_tasks", "--task", "return-reminders", stdout=StringIO(), stderr=error)
    assert PeriodicTaskRun.objects.get(name="return-reminders").last_error == "RuntimeError"
    assert "provider-credential-secret" not in error.getvalue()
