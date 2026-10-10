"""Admission of staff audit verification runs: normalize, dedupe, bound, snapshot.

Every request is asynchronous. Admission locks the makerspace row, closes a stale active
run, returns the same-fingerprint active run (deduplicated) or refuses a different one
(one active run per makerspace), preflights every work bound against database counts
while holding the audit scope session lock, then records an immutable root, its
QUEUED event and the ``audit.verification_requested`` audit row, and enqueues the task
after commit.
"""

import hashlib
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.audit import services as audit
from apps.audit.batches import scope_session_lock
from apps.audit.models import (
    AuditBatch,
    AuditBatchLeaf,
    AuditLog,
    AuditSigningKeyRotation,
    AuditVerificationRun,
    AuditVerificationRunEvent,
)
from apps.makerspaces.models import Makerspace

MAX_ROWS = 10_000
MAX_EXPANDED_LEAVES = 50_000
MAX_CHAIN_BATCHES = 2_500
MAX_ROTATIONS = 256
MAX_ANCHOR_READS = 2_760
SOFT_TIME_LIMIT = 120
HARD_TIME_LIMIT = 150
MAX_ATTEMPTS = 3
STALE_GRACE_SECONDS = 30

FILTER_FIELDS = {
    "action": "action_filter",
    "target_type": "target_type_filter",
    "target_id": "target_id_filter",
    "actor": "actor_filter",
    "start": "start_at",
    "end": "end_at",
}
State = AuditVerificationRunEvent.State


class VerificationRefused(Exception):
    status_code = 400
    code = "audit_verification_refused"


class NarrowAuditRange(VerificationRefused):
    code = "narrow_audit_range"


class VerificationScopeTooLarge(VerificationRefused):
    code = "audit_verification_scope_too_large"


class VerificationBusy(VerificationRefused):
    status_code = 409
    code = "audit_verification_busy"


def normalized_filters(validated):
    values = {column: validated.get(name) for name, column in FILTER_FIELDS.items()}
    for column in ("action_filter", "target_type_filter", "target_id_filter"):
        values[column] = values[column] or ""
    return values


def fingerprint(makerspace_id, filters):
    canonical = {
        key: (value.isoformat() if hasattr(value, "isoformat") else value)
        for key, value in sorted(filters.items())
    }
    payload = json.dumps([makerspace_id, canonical], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_rows(makerspace_id, filters, snapshot_max_id=None):
    rows = AuditLog.objects.filter(makerspace_id=makerspace_id)
    lookups = {
        "action_filter": "action", "target_type_filter": "target_type",
        "target_id_filter": "target_id", "actor_filter": "actor_id",
        "start_at": "created_at__gte", "end_at": "created_at__lt",
    }
    applied = {lookups[key]: value for key, value in filters.items() if value not in (None, "")}
    rows = rows.filter(**applied)
    if snapshot_max_id is not None:
        rows = rows.filter(pk__lte=snapshot_max_id)
    return rows


def run_filters(run):
    return {column: getattr(run, column) for column in FILTER_FIELDS.values()}


def work_bounds(makerspace_id, rows):
    """Database-derived work for a selection: (rows, leaves, batches, rotations, reads)."""
    selected = rows.count()
    batch_ids = AuditBatchLeaf.objects.filter(audit_log__in=rows).values("batch_id")
    leaves = AuditBatch.objects.filter(pk__in=batch_ids).aggregate(total=Sum("leaf_count"))
    chain = AuditBatch.objects.filter(makerspace_id=makerspace_id).count()
    rotations = AuditSigningKeyRotation.objects.filter(makerspace_id=makerspace_id).count()
    # activation + each rotation + each batch + the deleted-tail probe + the scope head.
    reads = 1 + rotations + chain + 2
    return selected, leaves["total"] or 0, chain, rotations, reads


def check_bounds(bounds):
    selected, leaves, chain, rotations, reads = bounds
    if selected > MAX_ROWS:
        raise NarrowAuditRange("Narrow the audit range to at most 10,000 rows.")
    if (
        leaves > MAX_EXPANDED_LEAVES or chain > MAX_CHAIN_BATCHES
        or rotations > MAX_ROTATIONS or reads > MAX_ANCHOR_READS
    ):
        raise VerificationScopeTooLarge("The verification scope exceeds a work bound.")


def latest_event(run):
    return run.events.order_by("-pk").first()


def append_event(run, state, attempt, **fields):
    return AuditVerificationRunEvent.objects.create(run=run, state=state, attempt=attempt, **fields)


def close_stale_runs(makerspace_id, now=None):
    cutoff = (now or timezone.now()) - timedelta(seconds=HARD_TIME_LIMIT + STALE_GRACE_SECONDS)
    for run in AuditVerificationRun.objects.filter(makerspace_id=makerspace_id):
        event = latest_event(run)
        if event is None or event.state not in AuditVerificationRunEvent.ACTIVE_STATES:
            continue
        if event.created_at <= cutoff:
            finish(run, State.TIMED_OUT, event.attempt, failure_code="stale_run")


def active_run(makerspace_id):
    for run in AuditVerificationRun.objects.filter(makerspace_id=makerspace_id).order_by("-pk"):
        event = latest_event(run)
        if event is not None and event.state in AuditVerificationRunEvent.ACTIVE_STATES:
            return run
    return None


def finish(run, state, attempt, **fields):
    event = append_event(run, state, attempt, **fields)
    audit.record(
        None, "audit.verification_finished", makerspace=run.makerspace, target=run,
        meta={"status": state},
    )
    return event


def request_run(actor, makerspace_id, validated):
    """Return ``(run, deduplicated)`` or raise a ``VerificationRefused`` subclass."""
    filters = normalized_filters(validated)
    digest = fingerprint(makerspace_id, filters)
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace_id)
        close_stale_runs(makerspace_id)
        current = active_run(makerspace_id)
        # Dedupe BEFORE snapshotting, so the first run's own audit row cannot defeat it.
        if current is not None:
            if current.filter_fingerprint == digest:
                return current, True
            raise VerificationBusy("Another verification is running for this makerspace.")
        with scope_session_lock(makerspace_id):
            rows = run_rows(makerspace_id, filters)
            check_bounds(work_bounds(makerspace_id, rows))
            snapshot = rows.aggregate(top=Max("pk"))["top"] or 0
        run = AuditVerificationRun.objects.create(
            makerspace=makerspace, requested_by=actor, snapshot_max_id=snapshot,
            filter_fingerprint=digest, **filters,
        )
        append_event(run, State.QUEUED, 0)
        audit.record(actor, "audit.verification_requested", makerspace=makerspace, target=run)
        transaction.on_commit(lambda: _enqueue(run.pk))
    return run, False


def _enqueue(run_id, countdown=0):
    from apps.audit.tasks_verification import run_audit_verification

    run_audit_verification.apply_async(args=[run_id], countdown=countdown)
