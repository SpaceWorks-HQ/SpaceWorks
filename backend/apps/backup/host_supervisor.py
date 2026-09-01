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
    parse_marker,
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

    def transition_bound(self, state, database, operation, *, readiness=None):
        """Advance a proven bound candidate without ever accepting an intent."""
        state = MarkerState(state)
        current = read_marker(
            self.marker_path,
            require_root_owned=self.require_root_owned,
        )
        current_database = current.require_bound_database()
        same_database = (
            current_database.name == database.name
            and current_database.oid == database.oid
        )
        identity_enrichment = (
            same_database
            and current_database.server_identity is None
            and database.server_identity is not None
            and current.state == MarkerState.CANDIDATE_PREPARATION
            and state == MarkerState.CANDIDATE_HEALTH
        )
        if current_database != database and not identity_enrichment:
            raise MarkerError(
                "Only the current bound database may change host marker state."
            )
        if (
            current.state == state
            and state in {MarkerState.NORMAL, MarkerState.ACKNOWLEDGED_NORMAL}
            and current.operation is None
        ):
            payload = marker_payload(state, database, readiness=readiness)
            if current != parse_marker(payload):
                raise MarkerError(
                    "Completed normal marker readiness facts changed on resume."
                )
            return payload
        payload = marker_payload(
            state,
            database,
            operation=(
                operation
                if state in {
                    MarkerState.CANDIDATE_PREPARATION,
                    MarkerState.CANDIDATE_HEALTH,
                    MarkerState.QUARANTINED_AFTER_CUTOVER,
                }
                else None
            ),
            readiness=readiness,
        )
        if current.state == state:
            if current != parse_marker(payload):
                raise MarkerError(
                    "A resumed marker transition changed its bound facts."
                )
            return payload
        if current.operation != operation:
            raise MarkerError(
                "Only the current bound operation may change host marker state."
            )
        allowed = {
            (MarkerState.CANDIDATE_PREPARATION, MarkerState.CANDIDATE_HEALTH),
            (MarkerState.CANDIDATE_HEALTH, MarkerState.QUARANTINED_AFTER_CUTOVER),
            (MarkerState.QUARANTINED_AFTER_CUTOVER, MarkerState.NORMAL),
            (
                MarkerState.QUARANTINED_AFTER_CUTOVER,
                MarkerState.ACKNOWLEDGED_NORMAL,
            ),
        }
        if (current.state, state) not in allowed:
            raise MarkerError("The host marker state transition is out of order.")
        return self._replace(payload)

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
