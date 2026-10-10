"""Idempotent schedule/claim/complete primitives. Never reclaim a committed claim.

A notification may have escaped before a worker died. Automatic claim expiry
would violate at-most-once dispatch. Claims therefore have no lease or retry.
"""

from datetime import datetime, timedelta, timezone as datetime_timezone
from contextlib import contextmanager
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.makerspaces.models import Makerspace
from apps.operations.models_reminders import ReminderSchedule
from apps.tenant_migration.gate_runtime import _boundary_shared_locks, tenant_write


@contextmanager
def _reminder_write(makerspace_id):
    """Reuse a validated dispatch boundary, or acquire the standalone write gate.

    The sweeper holds a shared advisory lock on a dedicated connection. Acquiring
    it again on the application connection can block behind a waiting migration
    writer which itself waits for the first lock. The gate's ContextVar identifies
    exactly which boundaries this execution context already holds, so no caller
    flag or fabricated actor can bypass the standalone gate.
    """
    if makerspace_id is None or not rbac.scope_for_scheduled_work(
        Makerspace.objects.all(), makerspace_id=makerspace_id, field="pk",
    ).exists():
        raise ValidationError("Reminder makerspace is unavailable for scheduled work.")
    if makerspace_id in _boundary_shared_locks.get():
        with transaction.atomic():
            yield
    else:
        with tenant_write(makerspace_id):
            yield


def _reminders(makerspace):
    return rbac.scope_for_scheduled_work(
        ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
    )


def utc_time(value):
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValidationError("Reminder timestamps must be timezone-aware.")
    try:
        return value.astimezone(datetime_timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValidationError("Reminder UTC timestamp is out of range.") from exc


def _identifier(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{name} must contain 1 to {maximum} characters.")
    return value


def schedule_reminders(*, makerspace, source, subject, kind, due_at, offsets=(0,)):
    """One identity per tenant/source/subject/kind/offset, even if due time moves.

    Only pending rows move with a changed due date. Completed or uncertain claims
    remain tombstones. For recurring subjects include the occurrence in subject.
    No subject content, email address or User FK is stored here.
    """
    source = _identifier(source, "Source", 80)
    subject = _identifier(subject, "Subject", 160)
    kind = _identifier(kind, "Kind", 80)
    due_at = utc_time(due_at)
    if not isinstance(offsets, (list, tuple)) or len(offsets) > 100:
        raise ValidationError("Offsets must be a list or tuple with at most 100 steps.")
    if any(type(offset) is not int or not -(2**31) <= offset < 2**31 for offset in offsets):
        raise ValidationError("Offsets must be signed 32-bit integral seconds.")
    try:
        times = {offset: due_at + timedelta(seconds=offset) for offset in offsets}
    except OverflowError as exc:
        raise ValidationError("Reminder time is out of range.") from exc
    with _reminder_write(makerspace.pk):
        rows = []
        for offset, remind_at in times.items():
            row, _ = _reminders(makerspace).get_or_create(
                makerspace=makerspace, source=source, subject=subject, kind=kind,
                offset_seconds=offset, defaults={"due_at": due_at, "remind_at": remind_at},
            )
            _reminders(makerspace).filter(
                pk=row.pk, makerspace=makerspace, state=ReminderSchedule.State.PENDING,
            ).update(due_at=due_at, remind_at=remind_at)
            row = _reminders(makerspace).get(pk=row.pk)
            rows.append(row)
        return tuple(rows)


def claim_reminders(*, makerspace, source, now=None, limit=200):
    """Commit disjoint claims with skip_locked, before calling the emit path.

    Call from autocommit: an outer transaction could roll back the claim after an
    external send. The gate's separate lock-only connection is safe to hold here.
    """
    if transaction.get_connection().in_atomic_block or not transaction.get_autocommit():
        raise RuntimeError("Reminder dispatch claims require autocommit.")
    source = _identifier(source, "Source", 80)
    now = utc_time(timezone.now() if now is None else now)
    if type(limit) is not int or limit < 1:
        raise ValidationError("Claim limit must be a positive integer.")
    with _reminder_write(makerspace.pk):
        rows = list(
            _reminders(makerspace).select_for_update(skip_locked=True)
            .filter(makerspace=makerspace, source=source,
                    state=ReminderSchedule.State.PENDING, remind_at__lte=now)
            .order_by("remind_at", "pk")[:limit]
        )
        for row in rows:
            row.state = ReminderSchedule.State.CLAIMED
            row.claim_token = uuid4()
            row.claimed_at = now
        updated = _reminders(makerspace).bulk_update(rows, ["state", "claim_token", "claimed_at"])
        if updated != len(rows):
            # RBAC visibility can change while the row locks are held. Never
            # return an in-memory token whose claim was not persisted.
            raise ValidationError("Reminder makerspace changed while claiming.")
    return tuple(rows)


def complete_reminder(*, makerspace, reminder_id, claim_token, now=None, failed=False):
    """Fenced, idempotent completion; wrong tenants/tokens never change a row."""
    now = utc_time(timezone.now() if now is None else now)
    state = ReminderSchedule.State.FAILED if failed else ReminderSchedule.State.COMPLETED
    if claim_token is None:
        return False
    with _reminder_write(makerspace.pk):
        queryset = _reminders(makerspace).filter(
            pk=reminder_id, makerspace=makerspace, claim_token=claim_token,
        )
        if queryset.filter(state=ReminderSchedule.State.CLAIMED).update(
            state=state, completed_at=now,
        ):
            return True
        return queryset.filter(state=state).exists()
