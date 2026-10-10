"""One verification attempt: orthogonal coverage, bounded work, typed retry semantics."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.audit import services as audit
from apps.audit import verification_runs as runs
from apps.audit.anchors import (
    AnchorConfigurationError,
    AnchorConflict,
    AnchorError,
    AnchorInvalidEvidence,
    AnchorReadBudgetExceeded,
    AnchorTransportError,
)
from apps.audit.integrity_scope import local_phase
from apps.audit.models import AuditLog, AuditVerificationRunEvent
from apps.audit.verification_execution import RetryAttempt, execute_attempt, fail_attempt
from tests.audit_batch_helpers import MemoryAnchorSink, activate_and_seal
from tests.audit_explorer_helpers import space

pytestmark = pytest.mark.django_db
State = AuditVerificationRunEvent.State


@pytest.fixture(autouse=True)
def _setup(monkeypatch, settings):
    settings.AUDIT_ATTESTATION_DEPLOYMENT_ID = "test-deployment-p10"
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = ""
    monkeypatch.setattr(runs, "_enqueue", lambda run_id, countdown=0: None)


def _rows(makerspace, count=3):
    for _ in range(count):
        audit.record(None, "audit.page", makerspace=makerspace, target=makerspace)


def _run(makerspace):
    run, _ = runs.request_run(None, makerspace.pk, {})
    return run


def _use_sink(monkeypatch, settings, sink):
    settings.AUDIT_ATTESTATION_ANCHOR_BACKEND = "http"
    monkeypatch.setattr(
        "apps.audit.integrity_scope.configured_sink", lambda read_budget=None: sink
    )


class FailingSink(MemoryAnchorSink):
    def __init__(self, exc, inner):
        super().__init__()
        self.anchors, self.rotations, self.exc = inner.anchors, inner.rotations, exc
        self.calls = 0

    def fetch(self, identity):
        self.calls += 1
        raise self.exc


def _sealed(makerspace, rows=3):
    _rows(makerspace, rows)
    sink = MemoryAnchorSink()
    activate_and_seal(makerspace.pk, sink)
    return sink


def test_unconfigured_anchor_is_not_configured_and_succeeds():
    makerspace = space("vtask-plain")
    _rows(makerspace)
    event = execute_attempt(_run(makerspace).pk)
    assert event.state == State.SUCCEEDED and event.attempt == 1
    assert event.row_count == 3 and event.mac_valid_count == 3
    assert event.unbatched_count == 3 and event.local_batch_verified_count == 0
    assert event.chain_status == "locally_verified" and event.anchor_status == "not_configured"
    assert AuditLog.objects.filter(action="audit.verification_finished", meta={"status": "SUCCEEDED"}).exists()


def test_sealed_and_anchored_rows_are_fully_covered(monkeypatch, settings):
    makerspace = space("vtask-anchored")
    sink = _sealed(makerspace)
    _use_sink(monkeypatch, settings, sink)
    event = execute_attempt(_run(makerspace).pk)
    assert event.state == State.SUCCEEDED, event.__dict__
    assert event.local_batch_verified_count == event.row_count > 0
    assert event.anchor_status == "externally_anchored"
    assert event.externally_anchored_count == event.row_count


def test_transport_failure_retries_then_terminates_incomplete(monkeypatch, settings):
    makerspace = space("vtask-transport")
    sink = FailingSink(AnchorTransportError("down"), _sealed(makerspace))
    _use_sink(monkeypatch, settings, sink)
    run = _run(makerspace)
    for _ in range(2):
        with pytest.raises(RetryAttempt):
            execute_attempt(run.pk)
    event = execute_attempt(run.pk)
    states = list(run.events.order_by("pk").values_list("state", "attempt"))
    assert states == [
        ("QUEUED", 0), ("RUNNING", 1), ("RETRYING", 1), ("RUNNING", 2), ("RETRYING", 2),
        ("RUNNING", 3), ("INCOMPLETE", 3),
    ]
    assert event.failure_code == "anchor_retry_exhausted" and event.anchor_status == "unavailable"
    assert event.local_batch_verified_count > 0  # local aggregates survive


@pytest.mark.parametrize(
    "exc,anchor_status",
    [(AnchorConflict("forked"), "invalid"), (AnchorInvalidEvidence("garbage"), "invalid")],
)
def test_invalid_evidence_never_retries(monkeypatch, settings, exc, anchor_status):
    makerspace = space(f"vtask-invalid-{anchor_status}-{type(exc).__name__.lower()}")
    _use_sink(monkeypatch, settings, FailingSink(exc, _sealed(makerspace)))
    run = _run(makerspace)
    event = execute_attempt(run.pk)
    assert event.state == State.SUCCEEDED and event.anchor_status == anchor_status
    assert not run.events.filter(state=State.RETRYING).exists()


@pytest.mark.parametrize("exc", [AnchorConfigurationError("401"), AnchorError("plain")])
def test_configuration_and_plain_base_errors_are_unavailable_without_retry(monkeypatch, settings, exc):
    makerspace = space(f"vtask-config-{type(exc).__name__.lower()}")
    _use_sink(monkeypatch, settings, FailingSink(exc, _sealed(makerspace)))
    run = _run(makerspace)
    event = execute_attempt(run.pk)
    assert event.state == State.INCOMPLETE and event.failure_code == "verification_unavailable"
    assert not run.events.filter(state=State.RETRYING).exists()


def test_read_budget_exhaustion_is_bounds_exceeded_without_retry(monkeypatch, settings):
    makerspace = space("vtask-budget")
    _use_sink(monkeypatch, settings, FailingSink(AnchorReadBudgetExceeded("cap"), _sealed(makerspace)))
    run = _run(makerspace)
    event = execute_attempt(run.pk)
    assert event.state == State.INCOMPLETE and event.failure_code == "verification_bounds_exceeded"
    assert not run.events.filter(state=State.RETRYING).exists()


def test_growth_after_admission_stops_before_loading_or_any_sink_call(monkeypatch, settings):
    makerspace = space("vtask-grew")
    sink = FailingSink(AnchorTransportError("must not be called"), _sealed(makerspace))
    _use_sink(monkeypatch, settings, sink)
    run = _run(makerspace)
    monkeypatch.setattr(runs, "MAX_ROWS", 0)
    event = execute_attempt(run.pk)
    assert event.state == State.INCOMPLETE and event.failure_code == "verification_bounds_exceeded"
    assert sink.calls == 0 and event.row_count == 0


def test_duplicate_delivery_after_terminal_is_a_no_op():
    makerspace = space("vtask-dup")
    run = _run(makerspace)
    execute_attempt(run.pk)
    assert execute_attempt(run.pk) is None
    assert run.events.count() == 3


def test_soft_time_limit_and_task_error_close_with_closed_codes():
    makerspace = space("vtask-fail")
    run = _run(makerspace)
    assert fail_attempt(run.pk, "soft_time_limit").state == State.TIMED_OUT
    other = space("vtask-fail-2")
    run2 = _run(other)
    runs.append_event(run2, State.RUNNING, 1)
    event = fail_attempt(run2.pk, "task_error")
    assert event.state == State.FAILED and event.failure_code == "task_error"


def test_local_phase_query_count_does_not_grow_with_distinct_batches():
    one_space, many_space = space("vtask-q1"), space("vtask-qn")
    sink = MemoryAnchorSink()
    _rows(one_space, 2)
    activate_and_seal(one_space.pk, sink)
    for _ in range(3):
        _rows(many_space, 2)
        activate_and_seal(many_space.pk, sink)

    def measure(makerspace):
        rows = list(AuditLog.objects.filter(makerspace=makerspace).order_by("pk"))
        with CaptureQueriesContext(connection) as captured:
            result = local_phase(makerspace.pk, rows)
        return len(captured.captured_queries), result

    one_queries, one = measure(one_space)
    many_queries, many = measure(many_space)
    assert len(many.batch_results) > len(one.batch_results) >= 1
    assert many_queries == one_queries


def test_a_stripped_mac_on_a_sealed_row_is_invalid():
    makerspace = space("vtask-strip")
    sink = MemoryAnchorSink()
    _rows(makerspace, 2)
    activate_and_seal(makerspace.pk, sink)
    rows = list(AuditLog.objects.filter(makerspace=makerspace).order_by("pk"))
    rows[0].row_mac = None  # in-memory tamper: the classifier sees a sealed row without a MAC
    result = local_phase(makerspace.pk, rows)
    assert result.counts["mac_invalid_count"] == 1
    assert result.first_audit_log_id == rows[0].pk



def test_each_attempt_gets_a_fresh_budget_capped_per_attempt(monkeypatch, settings):
    """3 attempts x 2,760 counted reads = at most 8,280 per run, never more per attempt."""
    from apps.audit import verification_execution as execution

    budgets = []
    real = execution.AnchorReadBudget

    def tracking(limit):
        budget = real(limit)
        budgets.append(budget)
        return budget

    monkeypatch.setattr(execution, "AnchorReadBudget", tracking)
    makerspace = space("vtask-fresh-budget")
    _use_sink(monkeypatch, settings, FailingSink(AnchorTransportError("down"), _sealed(makerspace)))
    run = _run(makerspace)
    for _ in range(2):
        with pytest.raises(RetryAttempt):
            execute_attempt(run.pk)
    execute_attempt(run.pk)
    assert len(budgets) == 3 and len({id(budget) for budget in budgets}) == 3
    assert all(budget.limit == runs.MAX_ANCHOR_READS == 2_760 for budget in budgets)
    assert sum(budget.limit for budget in budgets) == 8_280



class RotationFailingSink(MemoryAnchorSink):
    """Point reads succeed; only the cross-key transition read fails."""

    def __init__(self, exc, inner):
        super().__init__()
        self.anchors, self.rotations, self.exc = inner.anchors, inner.rotations, exc

    def fetch_rotation(self, identity):
        raise self.exc


def _rotated(makerspace):
    from apps.audit.batches import activate_scope, batch_envelope, seal_scope
    from apps.audit.rotations import (
        finalize_rotation, prepare_rotation, publish_rotation, scope_head,
    )

    sink = MemoryAnchorSink()
    old_key = activate_scope(makerspace.pk, sink)
    _rows(makerspace, 2)
    sink.publish(batch_envelope(seal_scope(makerspace.pk, old_key)))
    head_seq, head_root = scope_head(makerspace.pk)
    rotation, _ = prepare_rotation(
        makerspace.pk, actor=None, expected_fingerprint=old_key.fingerprint,
        expected_head_seq=head_seq, expected_head_root=head_root,
    )
    publish_rotation(rotation, sink)
    finalize_rotation(rotation, sink, actor=None)
    return sink


def test_rotation_conflict_is_invalid_and_never_retries(monkeypatch, settings):
    makerspace = space("vtask-rot-conflict")
    _use_sink(monkeypatch, settings, RotationFailingSink(AnchorConflict("forked"), _rotated(makerspace)))
    run = _run(makerspace)
    event = execute_attempt(run.pk)
    assert event.state == State.SUCCEEDED and event.anchor_status == "invalid"
    assert not run.events.filter(state=State.RETRYING).exists()


def test_rotation_transport_failure_retries(monkeypatch, settings):
    makerspace = space("vtask-rot-transport")
    _use_sink(monkeypatch, settings, RotationFailingSink(AnchorTransportError("down"), _rotated(makerspace)))
    run = _run(makerspace)
    with pytest.raises(RetryAttempt):
        execute_attempt(run.pk)
    assert run.events.filter(state=State.RETRYING, attempt=1).exists()


def test_rotated_scope_with_a_working_sink_is_externally_anchored(monkeypatch, settings):
    makerspace = space("vtask-rot-ok")
    _use_sink(monkeypatch, settings, _rotated(makerspace))
    event = execute_attempt(_run(makerspace).pk)
    assert event.state == State.SUCCEEDED, (event.chain_status, event.anchor_status)
    assert event.anchor_status == "externally_anchored"
