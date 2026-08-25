import json

import pytest
from django.db import connection, connections, transaction
from django.http import HttpResponse
from django.test import RequestFactory

from apps.tenant_migration import gate_locks
from apps.tenant_migration.gate_locks import (
    SOURCE_GATE_LOCK_NAMESPACE,
    acquire_exclusive,
    acquire_shared,
    shared_boundary,
)
from apps.tenant_migration.middleware import SourceMigrationGateMiddleware
from tests.tenant_migration.source_gate_helpers import make_space


pytestmark = pytest.mark.django_db(transaction=True)


def test_shared_writer_blocks_exclusive_and_exclusive_refuses_tenant_write(
    monkeypatch,
):
    space = make_space("mutual-exclusion")
    secondary = connections["default"].copy()
    dispatches = []
    middleware = SourceMigrationGateMiddleware(
        lambda _request: dispatches.append(True) or HttpResponse(status=204)
    )

    new_lock_connection = gate_locks._new_lock_connection

    def lock_connection_with_timeout():
        lock_connection = new_lock_connection()
        lock_connection.autocommit = True
        with lock_connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '100ms'")
        return lock_connection

    monkeypatch.setattr(
        gate_locks, "_new_lock_connection", lock_connection_with_timeout
    )
    try:
        with transaction.atomic():
            acquire_shared(space.pk)
            assert _try_xact_lock(secondary, "exclusive", space.pk) is False
        with transaction.atomic():
            acquire_exclusive(space.pk)
            assert _try_xact_lock(secondary, "shared", space.pk) is False
            response = middleware(
                RequestFactory().post(
                    f"/api/v1/public/{space.slug}/membership-requests"
                )
            )
            assert response.status_code == 503
            assert dispatches == []
        assert middleware(
            RequestFactory().post(
                f"/api/v1/public/{space.slug}/membership-requests"
            )
        ).status_code == 204
    finally:
        secondary.close()


def test_request_boundary_holds_lock_without_transacting_dispatch():
    space = make_space("request-boundary-lock")
    secondary = connections["default"].copy()
    observed = []

    def dispatch(_request):
        observed.append(transaction.get_connection().in_atomic_block)
        observed.append(_try_xact_lock(secondary, "exclusive", space.pk))
        return HttpResponse(status=204)

    try:
        response = SourceMigrationGateMiddleware(dispatch)(
            RequestFactory().post(
                f"/api/v1/public/{space.slug}/membership-requests"
            )
        )

        assert response.status_code == 204
        assert observed == [False, False]
        assert _try_xact_lock(secondary, "exclusive", space.pk) is True
    finally:
        secondary.close()


def test_request_boundary_releases_lock_when_dispatch_raises():
    space = make_space("request-boundary-exception")
    secondary = connections["default"].copy()

    def dispatch(_request):
        assert _try_xact_lock(secondary, "exclusive", space.pk) is False
        raise RuntimeError("dispatch failed")

    try:
        middleware = SourceMigrationGateMiddleware(dispatch)
        with pytest.raises(RuntimeError, match="dispatch failed"):
            middleware(
                RequestFactory().post(
                    f"/api/v1/public/{space.slug}/membership-requests"
                )
            )

        assert _try_xact_lock(secondary, "exclusive", space.pk) is True
    finally:
        secondary.close()


def test_nested_boundary_references_each_release_exactly_once():
    space = make_space("nested-boundary-lock")
    secondary = connections["default"].copy()
    try:
        with shared_boundary(space.pk) as outer:
            with shared_boundary(space.pk):
                outer.release()
                outer.release()
                assert _try_xact_lock(secondary, "exclusive", space.pk) is False
            assert _try_xact_lock(secondary, "exclusive", space.pk) is True
    finally:
        secondary.close()


def test_live_request_uses_no_session_lock_across_app_transaction_boundary():
    space = make_space("request-no-session-lock")
    secondary = connections["default"].copy()
    observed = []

    def dispatch(_request):
        observed.append(_current_app_connection_lock_count(space.pk))
        with transaction.atomic():
            observed.append(_current_app_connection_lock_count(space.pk))
        observed.append(_current_app_connection_lock_count(space.pk))
        observed.append(_try_xact_lock(secondary, "exclusive", space.pk))
        return HttpResponse(status=204)

    try:
        response = SourceMigrationGateMiddleware(dispatch)(
            RequestFactory().post(
                f"/api/v1/public/{space.slug}/membership-requests"
            )
        )

        assert response.status_code == 204
        assert observed == [0, 0, 0, False]
    finally:
        secondary.close()


def test_app_connection_reopen_cannot_release_or_strand_boundary_lock():
    space = make_space("boundary-app-connection-reopen")
    primary = transaction.get_connection()
    secondary = connections["default"].copy()
    try:
        with shared_boundary(space.pk):
            assert _try_xact_lock(secondary, "exclusive", space.pk) is False
            primary.close()
            with primary.cursor() as cursor:
                cursor.execute("SELECT 1")
            assert _try_xact_lock(secondary, "exclusive", space.pk) is False

        assert _try_xact_lock(secondary, "exclusive", space.pk) is True
    finally:
        secondary.close()


@pytest.mark.parametrize(
    "failure_mode", ("connection-failure", "backend-switch"),
)
def test_gate_guarantee_failure_refuses_before_dispatch(
    monkeypatch, failure_mode
):
    space = make_space("gate-unavailable")
    dispatches = []
    broken = (
        _BrokenLockConnection()
        if failure_mode == "connection-failure"
        else _LostLockConnection()
    )
    monkeypatch.setattr(gate_locks, "_new_lock_connection", lambda: broken)
    middleware = SourceMigrationGateMiddleware(
        lambda _request: dispatches.append(True) or HttpResponse(status=204)
    )

    response = middleware(
        RequestFactory().post(
            f"/api/v1/public/{space.slug}/membership-requests"
        )
    )

    assert response.status_code == 503
    assert json.loads(response.content)["code"] == (
        "tenant_migration_gate_unavailable"
    )
    assert dispatches == []
    assert broken.close_calls == 1


def _try_xact_lock(db_connection, mode, makerspace_id):
    function = {
        "exclusive": "pg_try_advisory_xact_lock",
        "shared": "pg_try_advisory_xact_lock_shared",
    }[mode]
    with db_connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {function}(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, makerspace_id],
        )
        return bool(cursor.fetchone()[0])


def _current_app_connection_lock_count(makerspace_id):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM pg_locks
            WHERE locktype = 'advisory' AND pid = pg_backend_pid()
              AND classid = %s AND objid = %s
            """,
            [SOURCE_GATE_LOCK_NAMESPACE, makerspace_id],
        )
        return cursor.fetchone()[0]


class _BrokenLockConnection:
    def __init__(self):
        self.close_calls = 0

    @property
    def autocommit(self):
        return False

    @autocommit.setter
    def autocommit(self, _enabled):
        raise RuntimeError("pooler cannot establish a lock transaction")

    def close(self):
        self.close_calls += 1


class _LostLockConnection(_BrokenLockConnection):
    def __init__(self):
        super().__init__()
        self.fetches = iter(((None, 101), (102, False)))

    @_BrokenLockConnection.autocommit.setter
    def autocommit(self, _enabled):
        pass

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, _query, _params):
        pass

    def fetchone(self):
        return next(self.fetches)
