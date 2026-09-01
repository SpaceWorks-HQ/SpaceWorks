"""Tenant-only recipient custody for Lane D, independent of platform access."""

import logging

from django.db import transaction
from django.utils import timezone

from .custody import RECIPIENT_COUNT_BELOW_FLOOR, RECIPIENT_FLOOR
from .models import MakerspaceTenantExitCustodyState as CustodyState
from .tenant_exit_custody_alarms import (
    ensure_delivery_intents_locked,
    required_intents_present_locked,
)


logger = logging.getLogger(__name__)


def sync_tenant_exit_custody_locked(custody_lock):
    """Recompute Lane D state after makerspace/recipient PK locks are held."""
    now = timezone.now()
    count = custody_lock.verified_recipient_count()
    current = (
        CustodyState.objects.select_for_update()
        .filter(makerspace_id=custody_lock.makerspace.pk)
        .first()
    )
    if count >= RECIPIENT_FLOOR:
        state, changed = _record_healthy(current, custody_lock.makerspace, now)
    else:
        target = (
            CustodyState.State.DEGRADED_ONE_RECIPIENT
            if count == 1
            else CustodyState.State.FLOOR_BREACHED_ZERO
        )
        state, changed = _record_breach(current, custody_lock, target, now)

    # The outbox rows, not successful SMTP, are the publication prerequisite. Resolve
    # them before this revision lock is released so a worker enqueue can be lost safely.
    state.makerspace = custody_lock.makerspace
    if state.state != CustodyState.State.HEALTHY:
        ensure_delivery_intents_locked(state)
    if changed and state.state != CustodyState.State.HEALTHY:
        transaction.on_commit(
            lambda mid=custody_lock.makerspace.pk: _schedule_alarm(mid),
            robust=True,
        )
    return state


def assert_tenant_exit_custody_ready_locked(custody_lock):
    state = sync_tenant_exit_custody_locked(custody_lock)
    if state.state == CustodyState.State.FLOOR_BREACHED_ZERO:
        raise RuntimeError(
            "A Lane D capture requires at least one verified tenant recipient."
        )
    if not required_intents_present_locked(state):
        raise RuntimeError(
            "Tenant-exit custody lacks a durable current-revision alarm intent."
        )
    return state


def _record_healthy(current, makerspace, now):
    if current is None:
        return CustodyState.objects.create(
            makerspace=makerspace,
            alarm_revision=1,
        ), True
    changed = (
        current.state != CustodyState.State.HEALTHY
        or bool(current.reason_code)
        or current.triggering_recipient_id is not None
    )
    if not changed:
        return current, False
    current.state = CustodyState.State.HEALTHY
    current.reason_code = ""
    current.cleared_at = now
    current.last_alarm_at = None
    current.triggering_recipient = None
    current.alarm_revision += 1
    current.save()
    return current, True


def _record_breach(current, custody_lock, target, now):
    fresh_episode = current is None or current.state == CustodyState.State.HEALTHY
    previous_reason = current.reason_code if current is not None else ""
    reason = custody_lock.reason_code or previous_reason or RECIPIENT_COUNT_BELOW_FLOOR
    changed = (
        current is None
        or current.state != target
        or current.reason_code != reason
    )
    if current is None:
        current = CustodyState(makerspace=custody_lock.makerspace)
    if fresh_episode:
        current.alarm_episode += 1
        current.entered_at = now
    if changed:
        current.alarm_revision += 1
        current.last_alarm_at = None
    current.state = target
    current.reason_code = reason
    current.cleared_at = None
    if custody_lock.triggering_recipient_id is not None:
        current.triggering_recipient_id = custody_lock.triggering_recipient_id
    current.save()
    return current, changed


def _schedule_alarm(makerspace_id):
    try:
        from .tasks import deliver_tenant_exit_custody_alarms_task

        deliver_tenant_exit_custody_alarms_task.delay(makerspace_id)
    except Exception:
        logger.exception(
            "tenant_exit_custody_alarm_enqueue_failed",
            extra={"makerspace_id": makerspace_id},
        )
