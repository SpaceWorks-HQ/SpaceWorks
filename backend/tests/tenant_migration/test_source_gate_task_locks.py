import pytest
from django.db import connections, transaction

from apps.makerspaces.models import MakerspaceMembership, MemberProfile
from apps.tenant_migration import gate_policy
from apps.tenant_migration.gate_locks import SOURCE_GATE_LOCK_NAMESPACE
from apps.tenant_migration.task_gate import TenantGateTask
from config.celery import app as celery_app
from tests.tenant_migration.source_gate_helpers import make_actor, make_space


pytestmark = pytest.mark.django_db(transaction=True)

_TASK_OBSERVATIONS = {}


@celery_app.task(
    base=TenantGateTask,
    name="tests.tenant_migration.observable_gate_task",
)
def observable_gate_task(makerspace_id):
    _TASK_OBSERVATIONS["external_call"]()


def test_task_external_call_holds_lock_without_opening_app_transaction(monkeypatch):
    space = make_space("task-boundary-lock")
    secondary = connections["default"].copy()
    observed = []

    def external_call():
        observed.append(transaction.get_connection().in_atomic_block)
        observed.append(_try_exclusive(secondary, space.pk))

    _register_observation(monkeypatch, external_call)
    try:
        observable_gate_task.apply(args=(space.pk,), throw=True).get()

        assert observed == [False, False]
        assert _try_exclusive(secondary, space.pk) is True
    finally:
        secondary.close()


def test_github_fetch_stays_outside_app_transaction_while_lock_is_held(
    settings, monkeypatch
):
    from apps.makerspaces import github_contributions
    from apps.makerspaces.tasks import refresh_github_contributions_task

    settings.GITHUB_API_TOKEN = "test-token"
    space = make_space("github-boundary-lock")
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=make_actor("github-boundary-lock"),
        role=MakerspaceMembership.Role.CUSTOM,
    )
    profile = MemberProfile.objects.create(
        membership=membership, github_username="octocat"
    )
    secondary = connections["default"].copy()
    observed = []

    def fetch_total(login):
        assert login == "octocat"
        observed.append(transaction.get_connection().in_atomic_block)
        observed.append(_try_exclusive(secondary, space.pk))
        return 42

    monkeypatch.setattr(github_contributions, "fetch_total", fetch_total)
    try:
        result = refresh_github_contributions_task()

        assert result == {
            "configured": True,
            "updated": 1,
            "unavailable": 0,
            "skipped": 0,
        }
        assert observed == [False, False]
        assert _try_exclusive(secondary, space.pk) is True
        profile.refresh_from_db()
        assert profile.github_contributions == 42
    finally:
        secondary.close()


def test_task_boundary_releases_lock_when_task_raises(monkeypatch):
    space = make_space("task-boundary-exception")
    secondary = connections["default"].copy()

    def external_call():
        assert _try_exclusive(secondary, space.pk) is False
        raise RuntimeError("task failed")

    _register_observation(monkeypatch, external_call)
    try:
        with pytest.raises(RuntimeError, match="task failed"):
            observable_gate_task.apply(args=(space.pk,), throw=True)

        assert _try_exclusive(secondary, space.pk) is True
    finally:
        secondary.close()


def _register_observation(monkeypatch, callback):
    monkeypatch.setitem(
        gate_policy.TASK_TENANT_RESOLVERS,
        observable_gate_task.name,
        ("makerspaces.Makerspace", 0, "pk"),
    )
    monkeypatch.setitem(_TASK_OBSERVATIONS, "external_call", callback)


def _try_exclusive(db_connection, makerspace_id):
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            [SOURCE_GATE_LOCK_NAMESPACE, makerspace_id],
        )
        return bool(cursor.fetchone()[0])
