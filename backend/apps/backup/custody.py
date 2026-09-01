"""Serialized archive-recipient custody state maintenance."""

import logging
from contextlib import contextmanager
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.makerspaces.models import Makerspace

from .models import (
    MakerspaceArchiveCustodyState,
    MakerspaceArchiveRecipient,
)


RECIPIENT_FLOOR = 2
RECIPIENT_COMPROMISED = "recipient_compromised"
RECIPIENT_COUNT_BELOW_FLOOR = "recipient_count_below_floor"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeploymentCustodySummary:
    below_floor_makerspace_ids: tuple[int, ...]
    zero_recipient_off_makerspace_ids: tuple[int, ...]

    @property
    def below_floor_count(self):
        return len(self.below_floor_makerspace_ids)


@dataclass
class MakerspaceCustodyLock:
    makerspace: Makerspace
    reason_code: str = ""
    triggering_recipient_id: int | None = None

    def recipient(self, recipient_id):
        """Return a recipient row already covered by this makerspace's locks."""
        return MakerspaceArchiveRecipient.objects.get(
            pk=recipient_id,
            makerspace_id=self.makerspace.pk,
        )

    def verified_recipient_count(self):
        return MakerspaceArchiveRecipient.objects.filter(
            makerspace_id=self.makerspace.pk,
            verified_at__isnull=False,
            revoked_at__isnull=True,
            compromised_at__isnull=True,
        ).count()

    def record_trigger(self, *, reason_code, recipient):
        self.reason_code = reason_code
        self.triggering_recipient_id = recipient.pk


@contextmanager
def with_makerspace_custody_lock(makerspace_id, *, sync_tenant_exit=True):
    """Lock makerspace then recipients, and sync custody before committing.

    Every count-changing caller performs its mutation and audit while yielded. A
    normal exit recomputes custody in the same short transaction; an exception
    rolls back both the mutation and any custody-state write.
    """
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace_id)
        # Force evaluation so every existing recipient lock is taken only after the
        # makerspace lock. Callers must not construct a competing lock order.
        tuple(
            MakerspaceArchiveRecipient.objects.select_for_update()
            .filter(makerspace_id=makerspace_id)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        custody_lock = MakerspaceCustodyLock(makerspace=makerspace)
        yield custody_lock
        _sync_custody_state(custody_lock)
        # Lane D's nested tenant-only envelope has a separate obligation. It must be
        # recomputed under the exact same makerspace-first/recipient-PK lock, even when
        # Part A truthfully records NOT_APPLICABLE because platform access is enabled.
        if sync_tenant_exit:
            from .tenant_exit_custody import sync_tenant_exit_custody_locked

            sync_tenant_exit_custody_locked(custody_lock)


def validate_deployment_custody():
    """Refresh custody alarms in deterministic tenant order before activation."""
    below_floor_ids = []
    zero_recipient_off_ids = []
    makerspace_ids = tuple(
        Makerspace.objects.order_by("pk").values_list("pk", flat=True)
    )
    for makerspace_id in makerspace_ids:
        with with_makerspace_custody_lock(makerspace_id) as custody:
            count = custody.verified_recipient_count()
            if (
                not custody.makerspace.superadmin_access_enabled
                and count < RECIPIENT_FLOOR
            ):
                below_floor_ids.append(makerspace_id)
            if not custody.makerspace.superadmin_access_enabled and count == 0:
                zero_recipient_off_ids.append(makerspace_id)

    summary = DeploymentCustodySummary(
        below_floor_makerspace_ids=tuple(below_floor_ids),
        zero_recipient_off_makerspace_ids=tuple(zero_recipient_off_ids),
    )
    return summary


def initialize_custody_state(makerspace_id):
    """Compute and persist a makerspace's custody state from its current recipients.

    Callers that create a makerspace need the derived row to exist without making any
    recipient change of their own. Entering and leaving the lock is what recomputes it;
    this wrapper exists so those call sites read as intent rather than as a `with`
    block with an empty body.
    """
    with with_makerspace_custody_lock(makerspace_id, sync_tenant_exit=False):
        pass


def _sync_custody_state(custody_lock):
    now = timezone.now()
    count = custody_lock.verified_recipient_count()
    current = (
        MakerspaceArchiveCustodyState.objects.select_for_update()
        .filter(makerspace=custody_lock.makerspace)
        .first()
    )

    if custody_lock.makerspace.superadmin_access_enabled:
        _record_not_applicable(current, custody_lock.makerspace, now)
        return

    if count >= RECIPIENT_FLOOR:
        _record_healthy(current, custody_lock.makerspace, now)
        return

    target_state = (
        MakerspaceArchiveCustodyState.State.DEGRADED_ONE_RECIPIENT
        if count == 1
        else MakerspaceArchiveCustodyState.State.FLOOR_BREACHED_ZERO
    )
    _record_breach(current, custody_lock, target_state, now)


def _record_healthy(current, makerspace, now):
    if current is None:
        MakerspaceArchiveCustodyState.objects.create(
            makerspace=makerspace,
            alarm_revision=1,
        )
        return
    if (
        current.state == MakerspaceArchiveCustodyState.State.HEALTHY
        and not current.reason_code
        and current.triggering_recipient_id is None
    ):
        return
    changed = (
        current.state != MakerspaceArchiveCustodyState.State.HEALTHY
        or bool(current.reason_code)
    )
    current.state = MakerspaceArchiveCustodyState.State.HEALTHY
    current.reason_code = ""
    current.cleared_at = now
    current.last_alarm_at = None
    current.triggering_recipient = None
    if changed:
        current.alarm_revision += 1
    current.save(
        update_fields=(
            "state",
            "reason_code",
            "cleared_at",
            "last_alarm_at",
            "triggering_recipient",
            "alarm_revision",
        )
    )


def _record_not_applicable(current, makerspace, now):
    if current is None:
        MakerspaceArchiveCustodyState.objects.create(
            makerspace=makerspace,
            state=MakerspaceArchiveCustodyState.State.NOT_APPLICABLE,
            cleared_at=now,
            alarm_revision=1,
        )
        return
    if (
        current.state == MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
        and not current.reason_code
        and current.triggering_recipient_id is None
        and current.cleared_at is not None
        and current.last_alarm_at is None
    ):
        return
    changed = (
        current.state != MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
        or bool(current.reason_code)
    )
    current.state = MakerspaceArchiveCustodyState.State.NOT_APPLICABLE
    current.reason_code = ""
    current.cleared_at = now
    current.last_alarm_at = None
    current.triggering_recipient = None
    if changed:
        current.alarm_revision += 1
    current.save()


def _record_breach(current, custody_lock, target_state, now):
    fresh_episode = (
        current is None
        or current.state in (
            MakerspaceArchiveCustodyState.State.HEALTHY,
            MakerspaceArchiveCustodyState.State.NOT_APPLICABLE,
        )
    )
    previous_reason = current.reason_code if current is not None else ""
    reason_code = (
        custody_lock.reason_code
        or previous_reason
        or RECIPIENT_COUNT_BELOW_FLOOR
    )
    state_changed = current is None or current.state != target_state
    reason_changed = current is None or current.reason_code != reason_code

    if current is None:
        current = MakerspaceArchiveCustodyState(makerspace=custody_lock.makerspace)
    if fresh_episode:
        current.alarm_episode += 1
        current.entered_at = now
    if fresh_episode or state_changed or reason_changed:
        current.last_alarm_at = None
    if state_changed or reason_changed:
        current.alarm_revision += 1

    current.state = target_state
    current.reason_code = reason_code
    current.cleared_at = None
    if custody_lock.triggering_recipient_id is not None:
        current.triggering_recipient_id = custody_lock.triggering_recipient_id
    current.save()
    if state_changed or reason_changed:
        transaction.on_commit(
            lambda mid=custody_lock.makerspace.pk: _schedule_custody_alarm(mid),
            robust=True,
        )


def _schedule_custody_alarm(makerspace_id):
    try:
        from .tasks import deliver_archive_custody_alarms_task

        deliver_archive_custody_alarms_task.delay(makerspace_id)
    except Exception:
        logger.exception(
            "archive_custody_alarm_enqueue_failed",
            extra={"makerspace_id": makerspace_id},
        )
