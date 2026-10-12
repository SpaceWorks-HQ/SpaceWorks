"""Short committed claims and token-fenced terminal writes."""

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.hardware_requests.models_replay import ReplayCommand
from apps.hardware_requests.replay_failures import ReplayFailure
from apps.hardware_requests.replay_records import audit_meta


def claim_locked(command):
    now = timezone.now()
    if command.state == ReplayCommand.State.CLAIMED and command.claimed_at > now - timedelta(
        seconds=settings.KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS,
    ):
        raise ReplayFailure("claim_in_progress")
    command.state = ReplayCommand.State.CLAIMED
    command.claim_token = uuid4()
    command.claimed_at = now
    command.claim_attempts += 1
    command.save(update_fields=["state", "claim_token", "claimed_at", "claim_attempts", "updated_at"])
    return command.claim_token


def complete_locked(command, *, failure=None):
    command.state = ReplayCommand.State.FAILED if failure else ReplayCommand.State.SUCCEEDED
    command.failure_code = failure.code if failure else None
    command.failure_detail = failure.detail if failure else None
    command.completed_at = timezone.now()
    command.claim_token = None
    command.claimed_at = None
    command.save()


def fail_locked(command, failure, lease):
    complete_locked(command, failure=failure)
    audit.record(command.actor, "kiosk.replay_failed", makerspace=command.makerspace,
                 target=command.station, meta={**audit_meta(command, lease), "failure_code": failure.code})


def release(command_id, token):
    # A stale executor can neither release nor fail a newer caller's claim.
    with transaction.atomic():
        return ReplayCommand.objects.filter(
            pk=command_id, state=ReplayCommand.State.CLAIMED, claim_token=token,
        ).update(state=ReplayCommand.State.PREPARED, claim_token=None, claimed_at=None, updated_at=timezone.now())


def fail_claim(command_id, token, failure, lease):
    with transaction.atomic():
        command = ReplayCommand.objects.select_for_update().get(pk=command_id)
        if command.state == ReplayCommand.State.CLAIMED and command.claim_token == token:
            fail_locked(command, failure, lease)
