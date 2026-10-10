"""Claim -> S3 promotion -> atomic domain effect + success, with fenced recovery."""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence import storage
from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.replay_claims import claim_locked, complete_locked, fail_claim, fail_locked, release
from apps.hardware_requests.replay_dispatch import dispatch
from apps.hardware_requests.replay_failures import ReplayFailure, TRANSIENT, mapped_failure
from apps.hardware_requests.replay_records import age, audit_meta, check_predecessor, lease_snapshot, ownership, result
from apps.tenant_migration.gate_runtime import assert_write_allowed

logger = logging.getLogger(__name__)


def _owned(identity, envelope):
    queryset = ReplayCommand.objects.select_for_update()
    command = queryset.filter(
        station_id=identity.station_id, station_session_id=identity.session_id,
        client_command_id=envelope["client_command_id"],
    ).first()
    if command is None:
        raise ReplayFailure("target_missing")
    ownership(command, identity, envelope)
    return command


def _live_command(command, identity, envelope):
    station, lease, user = identity.live(envelope["kind"])
    assert_write_allowed(station.makerspace_id)
    if command.makerspace_id != station.makerspace_id:
        raise ReplayFailure("session_mismatch")
    age(envelope, lease)
    if command.expires_at <= timezone.now():
        raise ReplayFailure("command_expired")
    check_predecessor(command)
    return station, lease, user


def execute(identity, envelope):
    failure = None
    # Only coordination is locked here. Workflows own their request/evidence/quota
    # lock order; holding makerspace/credential locks first would invert that order.
    with transaction.atomic():
        command = _owned(identity, envelope)
        try:
            station, lease, user = _live_command(command, identity, envelope)
        except ReplayFailure as exc:
            if exc.code not in TRANSIENT and command.state == ReplayCommand.State.PREPARED:
                fail_locked(command, exc, lease_snapshot(command))
            failure = exc
        if failure is None:
            if command.state == ReplayCommand.State.FAILED:
                raise ReplayFailure(command.failure_code)
            if command.state == ReplayCommand.State.SUCCEEDED:
                return result(command)
            token = claim_locked(command)
            audit.record(user, "kiosk.replay_claimed", makerspace=station.makerspace,
                         target=station, meta={**audit_meta(command, lease), "claim_attempts": command.claim_attempts})
    if failure is not None:
        raise failure
    try:
        # No command/request/loan row locks span this external I/O.
        if command.evidence_id is not None:
            finalized = storage.finalize_upload(command.evidence, settings.EVIDENCE_MAX_BYTES)
            if finalized is None:
                raise ReplayFailure("evidence_missing")
        with transaction.atomic():
            command = _owned(identity, envelope)
            if command.state != ReplayCommand.State.CLAIMED or command.claim_token != token:
                raise ReplayFailure("claim_in_progress")
            station, lease, user = _live_command(command, identity, envelope)
            dispatch(command, station, user, envelope)
            complete_locked(command)
            audit.record(user, "kiosk.replay_succeeded", makerspace=station.makerspace,
                         target=station, meta=audit_meta(command, lease))
            data = result(command)
        return data
    except Exception as exc:
        failure = mapped_failure(exc, envelope["kind"])
        if failure is None:
            # Log only identifiers and exception type, never QR/payload/secret text.
            logger.error("kiosk_replay_unexpected_failure", extra={
                "replay_id": str(command.pk), "error_type": type(exc).__name__,
            })
            failure = ReplayFailure("server_unavailable")
        if failure.code in TRANSIENT:
            release(command.pk, token)
        else:
            fail_claim(command.pk, token, failure, lease)
        raise failure from None
