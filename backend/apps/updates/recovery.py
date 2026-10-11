"""Timed recovery never steals the physical lock from a live host operation."""

from datetime import timedelta

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.updates.models import PlatformUpdateSettings
from apps.updates.errors import UpdateRefused

INTERRUPTED_MESSAGE = "The previous update was interrupted before it finished."
TIMEOUT_MESSAGE = "The update exceeded its running timeout; the host operation is no longer active."


def is_stuck(row, *, now=None):
    started = row.running_since or row.updated_at
    timeout = timedelta(seconds=getattr(django_settings, "UPDATE_RUNNING_TIMEOUT_SECONDS", 7200))
    return row.status == PlatformUpdateSettings.Status.RUNNING and (now or timezone.now()) > started + timeout


def mark_interrupted(row, *, actor=None, reason=INTERRUPTED_MESSAGE):
    target = row.target_version
    row.status = PlatformUpdateSettings.Status.FAILED
    row.target_version = ""
    row.running_since = None
    row.update_requested_at = None
    row.last_error = reason
    row.save()
    audit.record(actor, "platform.update_recovered", target=row, meta={"target_version": target, "reason": reason})


def recover_stuck_update(actor):
    from apps.backup.operation_lock import OperationLockUnavailable, deployment_operation_lock
    from apps.updates.services import _locked_settings

    # Check idempotency before reaching the filesystem, including an unavailable host mount.
    with transaction.atomic():
        row = _locked_settings()
        if row.status != PlatformUpdateSettings.Status.RUNNING:
            return row
        if not is_stuck(row):
            raise UpdateRefused("update_not_stuck", "The update has not exceeded its timeout.")
    try:
        with deployment_operation_lock():
            with transaction.atomic():
                row = _locked_settings()
                if is_stuck(row):
                    mark_interrupted(row, actor=actor, reason=TIMEOUT_MESSAGE)
                return row
    except OperationLockUnavailable as exc:
        raise UpdateRefused(
            "host_operation_active",
            "The host operation lock is busy or unavailable; recovery cannot release it safely.",
        ) from exc
