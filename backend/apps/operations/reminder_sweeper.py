"""One UTC sweeper for explicit reminder sources, with isolated tenant failures."""

import logging
from dataclasses import asdict
from datetime import tzinfo
from itertools import islice
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.makerspaces.local_time import to_local
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.notifications.emit import emit_notification
from apps.operations import reminder_registry
from apps.operations.reminder_services import (
    claim_reminders, complete_reminder, schedule_reminders, utc_time,
)
from apps.tenant_migration.gate_runtime import fanout_tenant_write

logger = logging.getLogger(__name__)


def run_reminder_sweep(*, now=None, limit=None, tz_resolver=None):
    """A limit per tenant/source keeps busy tenants from starving their neighbours.

    tz_resolver(makerspace) returns a ZoneInfo name or tzinfo; only presentation/source
    policy uses it; by default the makerspace local-time service supplies its zone.
    Due instants, offsets and comparisons always use UTC. Frozen and
    not-restored tenants reach the gate so they are counted, rather than filtered out.
    """
    sources = reminder_registry.registered_sources()
    if not sources:
        return {"dispatched": 0, "skipped": 0, "failed": 0}
    if transaction.get_connection().in_atomic_block or not transaction.get_autocommit():
        raise RuntimeError("Reminder sweeps require autocommit.")
    now = utc_time(timezone.now() if now is None else now)
    limit = settings.REMINDER_SWEEP_BATCH_SIZE if limit is None else limit
    if type(limit) is not int or limit < 1:
        raise ValueError("Reminder sweep batch size must be a positive integer.")
    counts = {"dispatched": 0, "skipped": 0, "failed": 0}
    tenants = rbac.scope_for_scheduled_work(Makerspace.objects.all(), field="pk").order_by("pk")
    for makerspace in tenants.iterator(chunk_size=100):
        try:
            with fanout_tenant_write(
                makerspace.pk, operation="reminder_sweep", counts=counts,
            ) as should_process:
                if not should_process:
                    continue
                name = tz_resolver(makerspace) if tz_resolver else to_local(makerspace, now).tzinfo
                local_tz = ZoneInfo(name) if isinstance(name, str) else name
                if not isinstance(local_tz, tzinfo):
                    raise ValueError("Reminder timezone resolver must return a timezone.")
                # Validate custom resolvers without converting any stored timestamp.
                now.astimezone(local_tz)
                for source in sources:
                    if not _source_enabled(makerspace, source):
                        counts["skipped"] += 1
                        continue
                    _run_source(makerspace, source, now, local_tz, limit, counts)
        except Exception as exc:  # one gate/source/timezone failure never stops other tenants
            counts["failed"] += 1
            logger.error("reminder_tenant_failed", extra={
                "makerspace_id": makerspace.pk, "failure_type": type(exc).__name__,
            })
    return counts


def _source_enabled(makerspace, source):
    return (
        makerspace is not None
        and module_enabled(makerspace, source.module)
        and module_enabled(makerspace, "notifications")
        and (not source.feature or feature_enabled(makerspace, source.feature))
    )


def _current_tenant(makerspace):
    return rbac.scope_for_scheduled_work(
        Makerspace.objects.all(), makerspace_id=makerspace.pk, field="pk",
    ).first()


def _run_source(makerspace, source, now, local_tz, limit, counts):
    for subject in islice(source.discover(makerspace, now, limit, local_tz), limit):
        schedule_reminders(
            makerspace=makerspace, source=source.key, subject=subject.subject,
            kind=subject.kind, due_at=subject.due_at, offsets=subject.offsets,
        )
    # Discovery can be long-running; do not claim using an old module/feature
    # snapshot after staff disabled this source during discovery.
    current = _current_tenant(makerspace)
    if not _source_enabled(current, source):
        counts["skipped"] += 1
        return
    makerspace = current
    for row in claim_reminders(makerspace=makerspace, source=source.key, now=now, limit=limit):
        failed = False
        try:
            message = source.build(makerspace, row, now, local_tz)
            current = _current_tenant(makerspace)
            if message is None or not _source_enabled(current, source):
                counts["skipped"] += 1
            else:
                if source.dispatch is None:
                    emit_notification(current, **asdict(message))
                    # The staff emitter has no delivery receipt.
                    counts["dispatched"] += 1
                else:
                    result = source.dispatch(current, row, message)
                    failed = bool(result and result.failed_counts)
                    if result and result.delivered_counts:
                        counts["dispatched"] += 1
                    elif not failed:
                        counts["skipped"] += 1
                    if failed:
                        counts["failed"] += 1
        except Exception as exc:
            failed = True
            counts["failed"] += 1
            logger.error("reminder_dispatch_failed", extra={
                "makerspace_id": makerspace.pk, "reminder_id": row.pk,
                "source": source.key, "failure_type": type(exc).__name__,
            })
        complete_reminder(
            makerspace=makerspace, reminder_id=row.pk, claim_token=row.claim_token,
            now=now, failed=failed,
        )
