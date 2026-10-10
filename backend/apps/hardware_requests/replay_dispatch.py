"""Resolve dependencies then delegate to the same validated online dispatcher."""

from apps.hardware_requests import kiosk_online_commands as online
from apps.hardware_requests.models import ReturnEvent
from apps.hardware_requests.replay_failures import ReplayFailure


def dispatch(command, station, user, envelope):
    payload = dict(envelope["payload"])
    if command.evidence_id is not None:
        payload["evidence_id"] = command.evidence_id
    if command.operation_kind == "direct_return" and "loan_id" not in payload:
        previous = command.predecessor
        while previous is not None:
            if previous.result_loan_id is not None:
                payload["loan_id"] = previous.result_loan_id
                break
            previous = previous.predecessor
        if "loan_id" not in payload:
            raise ReplayFailure("predecessor_missing")
    _result, refs = online.dispatch_validated(station=station, user=user,
                                             kind=command.operation_kind, payload=payload)
    command.result_request_id = refs.get("request_id")
    command.result_loan_id = refs.get("loan_id")
    if command.operation_kind.endswith("return"):
        command.result_return_event = ReturnEvent.objects.get(
            evidence_id=command.evidence_id, makerspace_id=station.makerspace_id,
        )
    if command.operation_kind == "direct_return" and command.subject_loan_id is None:
        command.subject_loan_id = payload["loan_id"]
