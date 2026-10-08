"""Verification runs are an immutable root plus an append-only, ordered event history."""

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from apps.audit.models import AuditVerificationRun, AuditVerificationRunEvent
from tests.audit_explorer_helpers import space, superadmin

pytestmark = pytest.mark.django_db
State = AuditVerificationRunEvent.State


def _run(makerspace, **overrides):
    values = {
        "makerspace": makerspace,
        "requested_by": None,
        "snapshot_max_id": 10,
        "filter_fingerprint": "f" * 64,
        **overrides,
    }
    return AuditVerificationRun.objects.create(**values)


def _event(run, state, attempt=0, **extra):
    return AuditVerificationRunEvent.objects.create(run=run, state=state, attempt=attempt, **extra)


def _refused(callable_):
    with pytest.raises((InternalError, IntegrityError, RuntimeError)):
        with transaction.atomic():
            callable_()


def test_root_and_events_reject_orm_update_and_delete():
    run = _run(space("vrun-orm"))
    event = _event(run, State.QUEUED)
    with pytest.raises(RuntimeError):
        run.save()
    with pytest.raises(RuntimeError):
        run.delete()
    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()


def test_database_refuses_raw_update_and_delete():
    run = _run(space("vrun-sql"))
    _event(run, State.QUEUED)
    statements = [
        ("UPDATE audit_auditverificationrun SET snapshot_max_id = 1 WHERE id = %s", run.pk),
        ("DELETE FROM audit_auditverificationrun WHERE id = %s", run.pk),
        ("UPDATE audit_auditverificationrunevent SET row_count = 9 WHERE run_id = %s", run.pk),
        ("DELETE FROM audit_auditverificationrunevent WHERE run_id = %s", run.pk),
    ]
    for sql, pk in statements:
        def execute(sql=sql, pk=pk):
            with connection.cursor() as cursor:
                cursor.execute(sql, [pk])
        _refused(execute)
    assert AuditVerificationRun.objects.filter(pk=run.pk).exists()


def test_legal_retry_sequence_up_to_attempt_three_then_terminal():
    run = _run(space("vrun-legal"))
    _event(run, State.QUEUED, 0)
    _event(run, State.RUNNING, 1)
    _event(run, State.RETRYING, 1)
    _event(run, State.RUNNING, 2)
    _event(run, State.RETRYING, 2)
    _event(run, State.RUNNING, 3)
    _event(run, State.INCOMPLETE, 3, failure_code="anchor_retry_exhausted")
    for state in (State.RUNNING, State.SUCCEEDED, State.QUEUED):
        _refused(lambda state=state: _event(run, state, 3))


@pytest.mark.parametrize(
    "sequence",
    [
        [(State.RUNNING, 1)],  # must start QUEUED(0)
        [(State.QUEUED, 1)],
        [(State.QUEUED, 0), (State.SUCCEEDED, 0)],  # QUEUED cannot finish directly
        [(State.QUEUED, 0), (State.RUNNING, 2)],
        [(State.QUEUED, 0), (State.RUNNING, 1), (State.SUCCEEDED, 2)],
        [(State.QUEUED, 0), (State.RUNNING, 1), (State.RETRYING, 1), (State.RUNNING, 3)],
    ],
)
def test_illegal_transitions_are_refused(sequence):
    run = _run(space("vrun-illegal"))
    *prefix, (state, attempt) = sequence
    for prior_state, prior_attempt in prefix:
        _event(run, prior_state, prior_attempt)
    _refused(lambda: _event(run, state, attempt))


def test_a_fourth_attempt_is_refused():
    run = _run(space("vrun-four"))
    _event(run, State.QUEUED, 0)
    for attempt in (1, 2, 3):
        _event(run, State.RUNNING, attempt)
        _event(run, State.RETRYING, attempt)
    _refused(lambda: _event(run, State.RUNNING, 4))
    _event(run, State.TIMED_OUT, 3)


@pytest.mark.parametrize("terminal", [State.SUCCEEDED, State.INCOMPLETE, State.FAILED, State.TIMED_OUT])
def test_every_terminal_state_is_final(terminal):
    run = _run(space(f"vrun-term-{terminal.lower()}"))
    _event(run, State.QUEUED, 0)
    _event(run, State.RUNNING, 1)
    _event(run, terminal, 1)
    _refused(lambda: _event(run, State.RETRYING, 1))


def test_actor_filter_is_a_positive_scalar_not_a_user_edge():
    makerspace = space("vrun-actor")
    assert _run(makerspace, actor_filter=None).actor_filter is None
    assert _run(makerspace, actor_filter=987_654_321).actor_filter == 987_654_321  # no such user
    _refused(lambda: _run(makerspace, actor_filter=0))
    field = AuditVerificationRun._meta.get_field("actor_filter")
    assert not field.is_relation


def test_requester_deletion_is_protected_but_actor_filter_never_blocks_it():
    makerspace = space("vrun-user")
    requester, filtered = superadmin("vrun-requester"), superadmin("vrun-filtered")
    _run(makerspace, requested_by=requester, actor_filter=filtered.pk)
    filtered.delete()  # a filter value is not a reference
    assert AuditVerificationRun.objects.filter(requested_by=requester).exists()


def test_authorized_purge_context_may_delete_events_then_root():
    run = _run(space("vrun-purge"))
    _event(run, State.QUEUED, 0)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL session_replication_role = 'replica'")
        AuditVerificationRunEvent.objects.filter(run=run).delete()
        AuditVerificationRun.objects.filter(pk=run.pk).delete()
    assert not AuditVerificationRun.objects.filter(pk=run.pk).exists()
