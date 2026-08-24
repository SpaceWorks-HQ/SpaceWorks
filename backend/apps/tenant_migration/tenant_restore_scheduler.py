"""External-scheduler control-plane callback contract for D7."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .tenant_restore_types import SchedulerFenceReceipt, TenantRestoreRefused


MAX_CALLBACK_TIMEOUT_SECONDS = 300


class ExternalSchedulerCallbacks:
    """Invoke one provider adapter executable with JSON stdin/stdout.

    The executable is the scheduler/provider control-plane integration. It must keep
    its own durable generation and receipts; this client never treats local process
    state, the image entrypoint, or the host marker as scheduler state.
    """

    def __init__(self, executable, *, required_jobs, timeout_seconds=60):
        if not isinstance(executable, str) or not executable.strip():
            raise TenantRestoreRefused("External scheduler callback configuration is invalid.")
        self.executable = str(Path(executable))
        try:
            jobs = tuple(required_jobs)
        except TypeError as exc:
            raise TenantRestoreRefused(
                "External scheduler callback configuration is invalid."
            ) from exc
        if (
            not jobs
            or any(not isinstance(job, str) or not job for job in jobs)
            or len(set(jobs)) != len(jobs)
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= MAX_CALLBACK_TIMEOUT_SECONDS
        ):
            raise TenantRestoreRefused("External scheduler callback configuration is invalid.")
        self.required_jobs = tuple(sorted(jobs))
        self.timeout_seconds = timeout_seconds

    def _call(self, action, payload):
        try:
            completed = subprocess.run(
                [self.executable, action],
                input=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                text=True,
                capture_output=True,
                check=True,
                timeout=self.timeout_seconds,
                close_fds=True,
            )
            response = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise TenantRestoreRefused(
                f"External scheduler {action} callback failed or timed out."
            ) from exc
        if not isinstance(response, dict):
            raise TenantRestoreRefused(
                f"External scheduler {action} returned an invalid response."
            )
        return response

    def stop(self, *, run_id, old_identity, old_generation):
        response = self._call("stop", {
            "run_id": run_id,
            "old_database_identity": old_identity,
            "old_pointer_generation": old_generation,
        })
        required = {"scheduler_identity", "pre_stop_generation", "triggers_disabled"}
        if set(response) != required or response["triggers_disabled"] is not True:
            raise TenantRestoreRefused("External scheduler stop did not disable every trigger.")
        if not all(
            isinstance(response.get(key), str) and response[key]
            for key in ("scheduler_identity", "pre_stop_generation")
        ):
            raise TenantRestoreRefused("External scheduler stop receipt is incomplete.")
        return response

    def fence(self, *, run_id, expected_scheduler_generation):
        return self._receipt(self._call("fence", {
            "run_id": run_id,
            "expected_scheduler_generation": expected_scheduler_generation,
        }))

    def status(self, *, run_id):
        return self._receipt(self._call("status", {"run_id": run_id}))

    def restart(self, *, run_id, new_identity, new_generation):
        response = self._call("restart", {
            "run_id": run_id,
            "new_database_identity": new_identity,
            "new_pointer_generation": new_generation,
        })
        expected = {
            "run_id": run_id,
            "database_identity": new_identity,
            "pointer_generation": new_generation,
            "enabled_jobs": list(self.required_jobs),
        }
        if response != expected:
            raise TenantRestoreRefused("External scheduler restart tuple conflicts.")
        return response

    def readiness(self, *, run_id, new_identity, new_generation):
        response = self._call("readiness", {
            "run_id": run_id,
            "new_database_identity": new_identity,
            "new_pointer_generation": new_generation,
        })
        expected = {
            "run_id": run_id,
            "database_identity": new_identity,
            "pointer_generation": new_generation,
            "enabled_jobs": list(self.required_jobs),
            "old_generation_dispatch_possible": False,
            "database_marker_observed": True,
            "cadence_verified": True,
        }
        if response != expected:
            raise TenantRestoreRefused("External scheduler readiness proof is incomplete.")
        return response

    def _receipt(self, response):
        required = {
            "scheduler_identity", "scheduler_generation", "triggers_disabled",
            "active_invocations", "registered_jobs",
        }
        if set(response) != required:
            raise TenantRestoreRefused("External scheduler fence receipt has an invalid shape.")
        jobs = response["registered_jobs"]
        if (
            response["triggers_disabled"] is not True
            or type(response["active_invocations"]) is not int
            or response["active_invocations"] != 0
            or not isinstance(jobs, list)
            or any(not isinstance(job, str) for job in jobs)
            or tuple(sorted(jobs)) != self.required_jobs
            or not isinstance(response["scheduler_identity"], str)
            or not response["scheduler_identity"]
            or not isinstance(response["scheduler_generation"], str)
            or not response["scheduler_generation"]
        ):
            raise TenantRestoreRefused("External scheduler fence receipt is stale or incomplete.")
        return SchedulerFenceReceipt(
            scheduler_identity=response["scheduler_identity"],
            scheduler_generation=response["scheduler_generation"],
            triggers_disabled=True,
            active_invocations=0,
            registered_jobs=self.required_jobs,
        )


def assert_same_fence_receipt(expected, actual):
    if expected != actual:
        raise TenantRestoreRefused("External scheduler fence receipt changed on re-read.")
    return actual


def receipt_from_detail(detail):
    return SchedulerFenceReceipt(
        scheduler_identity=detail["scheduler_identity"],
        scheduler_generation=detail["scheduler_generation"],
        triggers_disabled=detail["triggers_disabled"],
        active_invocations=detail["active_invocations"],
        registered_jobs=tuple(detail["registered_jobs"]),
    )
