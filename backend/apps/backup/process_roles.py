"""Marker-state admission policy for every process in the application image."""

from dataclasses import dataclass
from enum import StrEnum

from .host_marker import MarkerState


class ProcessRole(StrEnum):
    BACKEND = "backend"
    WORKER = "worker"
    BEAT = "beat"
    CRON = "cron"
    MIGRATE = "migrate"
    MANAGEMENT = "management"


@dataclass(frozen=True, slots=True)
class Admission:
    admitted: bool
    requires_capability: bool = False
    reason: str = ""


ALL_ROLES = frozenset(ProcessRole)
ADMITTED_BY_STATE = {
    MarkerState.NORMAL: ALL_ROLES,
    MarkerState.CANDIDATE_PREPARATION: frozenset({ProcessRole.MIGRATE}),
    MarkerState.CANDIDATE_HEALTH: frozenset({ProcessRole.BACKEND}),
    MarkerState.QUARANTINED_AFTER_CUTOVER: frozenset({ProcessRole.BACKEND}),
    MarkerState.ACKNOWLEDGED_NORMAL: ALL_ROLES,
}


def admission_for(state, role):
    state = MarkerState(state)
    role = ProcessRole(role)
    if role not in ADMITTED_BY_STATE[state]:
        return Admission(False, reason=f"role {role.value} is refused in {state.value}")
    return Admission(
        True,
        requires_capability=(
            state == MarkerState.CANDIDATE_HEALTH and role == ProcessRole.BACKEND
        ),
    )
