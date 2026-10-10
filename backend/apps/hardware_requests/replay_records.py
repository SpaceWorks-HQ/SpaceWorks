"""Ownership, stream links, safe result reconstruction and channel audit metadata."""

from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.utils import timezone

from apps.accounts import rbac
from apps.hardware_requests.kiosk_command_policy import OPERATIONS
from apps.hardware_requests.kiosk_online_commands import channel_meta
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_fingerprint import fingerprint


def ownership(command, identity, envelope):
    if (command.actor_id != identity.actor_id or command.operator_lease_id != identity.lease_id
            or command.station_version != identity.version):
        raise ReplayFailure("session_mismatch")
    if command.payload_fingerprint != fingerprint(envelope):
        raise ReplayFailure("idempotency_conflict")


def age(envelope, lease):
    now = timezone.now()
    timestamp = envelope["client_created_at"]
    if timestamp > now + timedelta(minutes=5):
        raise ReplayFailure("clock_skew")
    expires = min(lease.expires_at, timestamp + timedelta(seconds=settings.KIOSK_COMMAND_MAX_AGE_SECONDS))
    if expires <= now:
        raise ReplayFailure("command_expired")
    return expires


def scoped_targets(station, user, envelope):
    payload = envelope["payload"]
    action = next(iter(OPERATIONS[envelope["kind"]].actions - {rbac.Action.UPLOAD_EVIDENCE}))
    targets = {}
    for key, model, field in (("request_id", HardwareRequest, "subject_request"),
                              ("loan_id", PublicToolLoan, "subject_loan")):
        if key in payload:
            queryset = rbac.scope_by_action(user, action, model.objects.all()).filter(makerspace_id=station.makerspace_id)
            if model is PublicToolLoan:
                queryset = queryset.filter(source=PublicToolLoan.Source.ADMIN_DIRECT)
            target = queryset.filter(pk=payload[key]).first()
            if target is None:
                raise ReplayFailure("target_missing")
            targets[field] = target
    return targets


def check_predecessor(command):
    if command.predecessor_id is None:
        return
    predecessor = command.predecessor
    if predecessor.state == "failed":
        raise ReplayFailure("predecessor_failed")
    if predecessor.state != "succeeded":
        raise ReplayFailure("predecessor_pending")


def result(command):
    return {
        "replay_id": command.pk, "client_command_id": command.client_command_id,
        "state": command.state, "kind": command.operation_kind, "expires_at": command.expires_at,
        "evidence_id": command.evidence_id, "result_request_id": command.result_request_id,
        "result_loan_id": command.result_loan_id, "result_return_event_id": command.result_return_event_id,
        "failure_code": command.failure_code, "failure_detail": command.failure_detail,
    }


def audit_meta(command, lease):
    return channel_meta(
        lease, command.operation_kind, replay_id=str(command.pk), aggregate_id=str(command.aggregate_id),
        evidence_id=command.evidence_id, subject_request_id=command.subject_request_id,
        subject_loan_id=command.subject_loan_id, result_request_id=command.result_request_id,
        result_loan_id=command.result_loan_id, result_return_event_id=command.result_return_event_id,
    )


def lease_snapshot(command):
    return SimpleNamespace(pk=command.operator_lease_id, station_id=command.station_id,
                           station_version=command.station_version,
                           station_session_id=command.station_session_id)
