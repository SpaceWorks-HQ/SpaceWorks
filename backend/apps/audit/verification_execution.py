"""One Celery attempt of an audit verification run, and its terminal mapping.

The attempt appends RUNNING in a short transaction, recomputes the work bounds and
classifies the filtered rows inside one REPEATABLE READ snapshot, then reads anchors
under the audit scope session lock with a fresh per-attempt read budget, and appends
exactly one outcome event. Retryability is decided only by the closed internal cause
``anchor_transport`` (set from ``AnchorTransportError``) or a database error -- never by
catching the compatibility ``AnchorError`` base or by a public status.
"""

import logging

from django.db import OperationalError, connection, transaction

from apps.audit.anchors import AnchorReadBudget, AnchorReadBudgetExceeded
from apps.audit.batches import scope_session_lock
from apps.audit.integrity_anchor_errors import ANCHOR_TRANSPORT
from apps.audit.integrity_scope import anchor_phase, local_phase
from apps.audit.models import AuditVerificationRun, AuditVerificationRunEvent

from . import verification_runs as runs

logger = logging.getLogger(__name__)
State = AuditVerificationRunEvent.State
COUNT_FIELDS = (
    "row_count", "mac_valid_count", "unattested_count", "mac_invalid_count",
    "mac_unavailable_count", "unbatched_count", "local_batch_verified_count",
    "batch_invalid_count", "batch_unavailable_count", "externally_anchored_count",
)


class RetryAttempt(Exception):
    """Ask the task to schedule the next attempt (the RETRYING event is already written)."""


def _start_attempt(run_id):
    with transaction.atomic():
        run = AuditVerificationRun.objects.select_for_update().get(pk=run_id)
        latest = runs.latest_event(run)
        if latest is None or latest.state not in {State.QUEUED, State.RETRYING}:
            return None, None  # duplicate delivery or already terminal
        attempt = latest.attempt + 1
        runs.append_event(run, State.RUNNING, attempt)
    return run, attempt


def _snapshot(run):
    filters = runs.run_filters(run)
    # Only an outermost transaction can choose its isolation level; under a test's
    # wrapping transaction this is a savepoint and inherits the outer snapshot.
    outermost = not connection.in_atomic_block
    with transaction.atomic():
        if outermost:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        rows_qs = runs.run_rows(run.makerspace_id, filters, run.snapshot_max_id)
        try:
            runs.check_bounds(runs.work_bounds(run.makerspace_id, rows_qs))
        except runs.VerificationRefused:
            return None  # grew after admission: load nothing, call no sink
        rows = list(rows_qs.order_by("pk"))
        return local_phase(run.makerspace_id, rows)


def _fields(result):
    return {
        **{name: result.counts.get(name, 0) for name in COUNT_FIELDS},
        "chain_status": result.chain_status,
        "anchor_status": result.anchor_status,
        "first_audit_log_id": result.first_audit_log_id,
        "first_batch_seq": result.first_batch_seq,
    }


def _terminal(result):
    if result.anchor_status == "unavailable" or result.chain_status == "unavailable":
        return State.INCOMPLETE, "verification_unavailable"
    if result.counts.get("mac_unavailable_count") or result.counts.get("batch_unavailable_count"):
        return State.INCOMPLETE, "verification_unavailable"
    return State.SUCCEEDED, ""


def execute_attempt(run_id):
    run, attempt = _start_attempt(run_id)
    if run is None:
        return None
    try:
        with scope_session_lock(run.makerspace_id):
            result = _snapshot(run)
            if result is None:
                return runs.finish(run, State.INCOMPLETE, attempt,
                                   failure_code="verification_bounds_exceeded")
            try:
                anchor_phase(run.makerspace_id, result,
                             read_budget=AnchorReadBudget(runs.MAX_ANCHOR_READS))
            except AnchorReadBudgetExceeded:
                result.anchor_status = "unavailable"
                return runs.finish(run, State.INCOMPLETE, attempt,
                                   failure_code="verification_bounds_exceeded", **_fields(result))
    except OperationalError:
        logger.exception("audit_verification_database_error", extra={"run_id": run_id})
        if attempt < runs.MAX_ATTEMPTS:
            runs.append_event(run, State.RETRYING, attempt)
            raise RetryAttempt() from None
        return runs.finish(run, State.FAILED, attempt, failure_code="database_retry_exhausted")
    if result.cause == ANCHOR_TRANSPORT:
        if attempt < runs.MAX_ATTEMPTS:
            runs.append_event(run, State.RETRYING, attempt, **_fields(result))
            raise RetryAttempt()
        return runs.finish(run, State.INCOMPLETE, attempt,
                           failure_code="anchor_retry_exhausted", **_fields(result))
    state, code = _terminal(result)
    return runs.finish(run, state, attempt, failure_code=code, **_fields(result))


def fail_attempt(run_id, failure_code):
    """Close a RUNNING attempt after a soft time limit or an unexpected error."""
    run = AuditVerificationRun.objects.filter(pk=run_id).first()
    if run is None:
        return None
    latest = runs.latest_event(run)
    if latest is None or latest.state not in AuditVerificationRunEvent.ACTIVE_STATES:
        return latest
    state = State.TIMED_OUT if failure_code == "soft_time_limit" else State.FAILED
    if latest.state == State.QUEUED:
        state = State.TIMED_OUT  # QUEUED may only time out
    return runs.finish(run, state, latest.attempt, failure_code=failure_code)
