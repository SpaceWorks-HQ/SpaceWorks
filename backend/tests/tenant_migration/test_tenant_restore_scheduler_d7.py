import json
import subprocess
import uuid

import pytest

from apps.backup.host_run_ledger import RunLedger
from apps.tenant_migration.tenant_restore_activation import start_serving
from apps.tenant_migration.tenant_restore_scheduler import (
    ExternalSchedulerCallbacks,
    assert_same_fence_receipt,
)
from apps.tenant_migration.tenant_restore_types import (
    RestoreInputs,
    SchedulerFenceReceipt,
    TenantRestoreRefused,
)


JOBS = ("daily-maintenance", "tenant-custody")


def adapter(monkeypatch, responses):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv[-1], json.loads(kwargs["input"])))
        value = responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    monkeypatch.setattr(subprocess, "run", run)
    return ExternalSchedulerCallbacks("/provider/control", required_jobs=JOBS), calls


def receipt(*, generation="fence-2", active=0):
    return {
        "scheduler_identity": "provider/scheduler",
        "scheduler_generation": generation,
        "triggers_disabled": True,
        "active_invocations": active,
        "registered_jobs": list(JOBS),
    }


def test_stop_fence_and_status_require_a_stable_zero_active_receipt(monkeypatch):
    callbacks, calls = adapter(monkeypatch, [
        {
            "scheduler_identity": "provider/scheduler",
            "pre_stop_generation": "fence-1",
            "triggers_disabled": True,
        },
        receipt(),
        receipt(),
    ])
    stopped = callbacks.stop(
        run_id="run", old_identity={"database_uuid": "old"}, old_generation=8
    )
    fenced = callbacks.fence(
        run_id="run", expected_scheduler_generation=stopped["pre_stop_generation"]
    )

    assert_same_fence_receipt(fenced, callbacks.status(run_id="run"))
    assert [action for action, _payload in calls] == ["stop", "fence", "status"]


def test_stale_or_non_drained_fence_receipt_refuses(monkeypatch):
    callbacks, _calls = adapter(monkeypatch, [receipt(active=1)])

    with pytest.raises(TenantRestoreRefused, match="stale or incomplete"):
        callbacks.fence(run_id="run", expected_scheduler_generation="fence-1")


def test_boolean_active_count_is_not_accepted_as_numeric_zero(monkeypatch):
    callbacks, _calls = adapter(monkeypatch, [receipt(active=False)])

    with pytest.raises(TenantRestoreRefused, match="stale or incomplete"):
        callbacks.fence(run_id="run", expected_scheduler_generation="fence-1")


@pytest.mark.parametrize("timeout", [True, "60", 0, 301])
def test_callback_timeout_requires_a_bounded_number(timeout):
    with pytest.raises(TenantRestoreRefused, match="configuration is invalid"):
        ExternalSchedulerCallbacks(
            "/provider/control", required_jobs=JOBS, timeout_seconds=timeout
        )


def test_callback_crash_is_retryable_with_the_same_durable_tuple(monkeypatch):
    callbacks, calls = adapter(monkeypatch, [
        subprocess.TimeoutExpired("provider", 60),
        receipt(),
    ])
    with pytest.raises(TenantRestoreRefused, match="failed or timed out"):
        callbacks.fence(run_id="run", expected_scheduler_generation="fence-1")
    callbacks.fence(run_id="run", expected_scheduler_generation="fence-1")

    assert calls[0] == calls[1]


def test_restart_tuple_conflict_and_old_generation_dispatch_both_refuse(monkeypatch):
    identity = {"database_uuid": "new"}
    wrong_restart = {
        "run_id": "other", "database_identity": identity,
        "pointer_generation": 9, "enabled_jobs": list(JOBS),
    }
    readiness = {
        "run_id": "run", "database_identity": identity,
        "pointer_generation": 9, "enabled_jobs": list(JOBS),
        "old_generation_dispatch_possible": True,
        "database_marker_observed": True, "cadence_verified": True,
    }
    callbacks, _calls = adapter(monkeypatch, [wrong_restart, readiness])

    with pytest.raises(TenantRestoreRefused, match="tuple conflicts"):
        callbacks.restart(run_id="run", new_identity=identity, new_generation=9)
    with pytest.raises(TenantRestoreRefused, match="readiness proof"):
        callbacks.readiness(run_id="run", new_identity=identity, new_generation=9)


def test_readiness_requires_the_new_marker_and_exact_generation(monkeypatch):
    identity = {"database_uuid": "new"}
    response = {
        "run_id": "run", "database_identity": identity,
        "pointer_generation": 9, "enabled_jobs": list(JOBS),
        "old_generation_dispatch_possible": False,
        "database_marker_observed": True, "cadence_verified": True,
    }
    callbacks, _calls = adapter(monkeypatch, [response])

    assert callbacks.readiness(
        run_id="run", new_identity=identity, new_generation=9
    )["database_marker_observed"] is True


def test_restart_crash_is_refenced_before_retry_and_writers_start_last(tmp_path):
    run_id = str(uuid.uuid4())
    run = RunLedger(
        tmp_path / "run.jsonl", run_id=run_id, artifact_sha256="a" * 64
    )
    initial = receipt()
    begun = run.begin("external-scheduler-fence", initial)
    run.finish(begun, initial)

    class Scheduler:
        state = "fenced"
        restart_calls = 0
        fence_calls = 0

        def status(self, **_kwargs):
            generation = "fence-2" if self.state == "fenced" else "enabled-3"
            return SchedulerFenceReceipt(
                "provider/scheduler", generation, self.state == "fenced", 0, JOBS
            )

        def stop(self, **_kwargs):
            self.state = "stopped"
            return {"pre_stop_generation": "enabled-3"}

        def fence(self, **_kwargs):
            self.fence_calls += 1
            self.state = "fenced"
            return self.status()

        def restart(self, **_kwargs):
            self.restart_calls += 1
            self.state = "enabled"
            if self.restart_calls == 1:
                raise TenantRestoreRefused("callback crashed")

        def readiness(self, **_kwargs):
            return {"database_marker_observed": True}

    class Writers:
        starts = 0

        def start(self, _sibling, _generation):
            self.starts += 1
            return {"marker_observed": True}

    scheduler = Scheduler()
    writers = Writers()
    inputs = RestoreInputs(run_id, "a" * 64, str(uuid.uuid4()), "a@example.test")
    cutover = {
        "new_database_marker": {"database_uuid": "new"}, "new_generation": 9
    }
    with pytest.raises(TenantRestoreRefused, match="callback crashed"):
        start_serving(
            run, inputs=inputs, sibling=object(), cutover_detail=cutover,
            writers=writers, scheduler=scheduler,
        )
    assert writers.starts == 0

    start_serving(
        run, inputs=inputs, sibling=object(), cutover_detail=cutover,
        writers=writers, scheduler=scheduler,
    )
    assert scheduler.fence_calls == 1
    assert scheduler.restart_calls == 2
    assert writers.starts == 1
