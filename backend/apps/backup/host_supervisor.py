"""Operation-lock boundary shared by future Lane D and Lane E supervisors."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .host_run_ledger import RunLedger
from .host_marker import (
    MarkerError,
    MarkerStage,
    MarkerState,
    marker_payload,
    read_marker,
    write_marker_fsynced,
)
from .operation_lock import host_operation_lock


@dataclass(frozen=True, slots=True)
class SupervisorSession:
    lock_handle: object
    ledger: RunLedger
    resume: object

    def terminal(self, capability_journal, *, reason="terminal-operation"):
        """Invalidate launch authority before recording/releasing terminal state."""
        return capability_journal.invalidate_all(reason)


class HostMarkerTransition:
    """Privileged two-stage marker writer held behind the host operation lock."""

    def __init__(
        self,
        marker_path,
        capability_journal,
        *,
        require_root_owned=True,
        crash_hook=None,
    ):
        self.marker_path = Path(marker_path)
        self.capability_journal = capability_journal
        self.require_root_owned = require_root_owned
        self.crash_hook = crash_hook

    def write_intent(self, operation):
        if self.marker_path.exists():
            current = read_marker(
                self.marker_path,
                require_root_owned=self.require_root_owned,
            )
            if (
                current.stage == MarkerStage.INTENT
                and current.operation != operation
            ):
                raise MarkerError("Host marker intent belongs to a different operation.")
        return self._replace(marker_payload(
            MarkerState.CANDIDATE_PREPARATION,
            None,
            operation=operation,
        ))

    def bind_database(self, database, operation):
        current = read_marker(
            self.marker_path,
            require_root_owned=self.require_root_owned,
        )
        if current.stage != MarkerStage.INTENT or current.operation != operation:
            raise MarkerError("Only the current operation intent may be bound.")
        return self._replace(marker_payload(
            MarkerState.CANDIDATE_PREPARATION,
            database,
            operation=operation,
        ))

    def _replace(self, payload):
        # Invalidation precedes both stages. A crash can only narrow authority;
        # transition recovery never silently re-arms a launch capability.
        self.capability_journal.invalidate_all("marker-transition")
        write_marker_fsynced(
            self.marker_path,
            payload,
            crash_hook=self.crash_hook,
            require_root_owned=self.require_root_owned,
        )
        return payload


@contextmanager
def supervise_run(
    ops_dir,
    *,
    run_id,
    artifact_sha256,
    phases,
    blocking=False,
    require_root_owned=True,
):
    """Acquire exclusion before even reading the resumable preflight state."""
    with host_operation_lock(
        ops_dir,
        blocking=blocking,
        require_root_owned=require_root_owned,
    ) as lock_handle:
        ledger = RunLedger(
            Path(ops_dir, "runs", f"{run_id}.jsonl"),
            run_id=run_id,
            artifact_sha256=artifact_sha256,
        )
        resume = ledger.resume_decision(phases)
        yield SupervisorSession(lock_handle, ledger, resume)
