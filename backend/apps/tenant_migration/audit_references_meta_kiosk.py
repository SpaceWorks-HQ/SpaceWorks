"""Audit meta references for kiosk Stations, sessions and operator leases (phase 9b).

Station/evidence/request/loan identifiers REMAP to the exported target row. Station
session and operator-lease identifiers are SOURCE_LOCAL_SNAPSHOT: both tables are
omitted and never travel, so the ids stay as source history only. Merged into
``AUDIT_META_REFERENCES`` by ``audit_references_meta``.
"""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT

_STATION_ACTIONS = (
    "kiosk.station_created",
    "kiosk.station_pin_rotated",
    "kiosk.station_pin_revealed",
    "kiosk.station_disabled",
    "kiosk.station_pin_failed",
    "kiosk.station_session_started",
    "kiosk.operator_lease_issued",
    "kiosk.operator_lease_revoked",
    "kiosk.work_package_issued",
    "kiosk.evidence_upload_issued",
    "kiosk.online_command_executed",
)
_SESSION_ACTIONS = (
    "kiosk.station_session_started",
    "kiosk.operator_lease_issued",
    "kiosk.operator_lease_revoked",
    "kiosk.work_package_issued",
    "kiosk.evidence_upload_issued",
    "kiosk.online_command_executed",
)
_LEASE_ACTIONS = _SESSION_ACTIONS[1:]
_RESULT_ACTIONS = ("kiosk.work_package_issued", "kiosk.online_command_executed")


def _edges(disposition, model, pairs):
    return {edge: AuditReference(disposition, model) for edge in pairs}


KIOSK_AUDIT_EDGES = {
    **_edges(R, "makerspaces.Station", ((a, "station_id") for a in _STATION_ACTIONS)),
    **_edges(S, None, ((a, "station_session_id") for a in _SESSION_ACTIONS)),
    **_edges(S, None, ((a, "operator_lease_id") for a in _LEASE_ACTIONS)),
    **_edges(
        R, "hardware_requests.HardwareRequest",
        ((a, "request_id") for a in _RESULT_ACTIONS),
    ),
    **_edges(
        R, "hardware_requests.PublicToolLoan",
        ((a, "loan_id") for a in _RESULT_ACTIONS),
    ),
    **_edges(
        R, "evidence.EvidencePhoto",
        (
            ("kiosk.evidence_upload_issued", "evidence_id"),
            ("kiosk.online_command_executed", "evidence_id"),
        ),
    ),
}

_REPLAY_ACTIONS = ("kiosk.replay_prepared", "kiosk.replay_claimed", "kiosk.replay_succeeded", "kiosk.replay_failed")
for _field, _model in (
    ("station_id", "makerspaces.Station"), ("evidence_id", "evidence.EvidencePhoto"),
    ("subject_request_id", "hardware_requests.HardwareRequest"),
    ("subject_loan_id", "hardware_requests.PublicToolLoan"),
    ("result_request_id", "hardware_requests.HardwareRequest"),
    ("result_loan_id", "hardware_requests.PublicToolLoan"),
    ("result_return_event_id", "hardware_requests.ReturnEvent"),
):
    KIOSK_AUDIT_EDGES.update(_edges(R, _model, ((a, _field) for a in _REPLAY_ACTIONS)))
for _field in ("replay_id", "operator_lease_id", "station_session_id", "aggregate_id"):
    KIOSK_AUDIT_EDGES.update(_edges(S, None, ((a, _field) for a in _REPLAY_ACTIONS)))
