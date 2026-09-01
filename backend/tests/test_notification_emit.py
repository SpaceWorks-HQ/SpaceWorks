import pytest
from django.utils import timezone

from apps.notifications.emit import emit_notification
from apps.notifications.models import Notification
from apps.operations.models import StocktakeSession
from apps.operations.services_stocktake import complete_stocktake
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db


def _enable_notifications(makerspace):
    makerspace.enabled_modules = list(makerspace.enabled_modules) + ["notifications"]
    makerspace.save(update_fields=["enabled_modules"])


def _disable_notifications(makerspace):
    # `notifications` is a registered, installable module now, so a test asserting the
    # disabled path has to turn it off rather than rely on it being unreachable.
    makerspace.enabled_modules = [
        key for key in makerspace.enabled_modules if key != "notifications"
    ]
    makerspace.save(update_fields=["enabled_modules"])


def test_emit_creates_row_when_module_enabled(django_capture_on_commit_callbacks):
    space = make_space("emit-on")
    _enable_notifications(space)
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, title="Hello", event="test.event", level="warning", body="Body")
    row = Notification.objects.get(makerspace=space)
    assert row.title == "Hello"
    assert row.event == "test.event"
    assert row.level == "warning"


def test_emit_noop_when_module_disabled(django_capture_on_commit_callbacks):
    space = make_space("emit-off")
    _disable_notifications(space)
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, title="Hello", event="test.event")
    assert not Notification.objects.filter(makerspace=space).exists()


def test_emit_is_fail_safe(monkeypatch, django_capture_on_commit_callbacks):
    space = make_space("emit-failsafe")
    _enable_notifications(space)

    def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(Notification.objects, "create", boom)
    # Must not raise even though the create fails inside the on_commit callback.
    with django_capture_on_commit_callbacks(execute=True):
        emit_notification(space, title="Hello", event="test.event")
    assert not Notification.objects.filter(makerspace=space).exists()


def test_stocktake_completion_emits_notification(django_capture_on_commit_callbacks):
    space = make_space("emit-stocktake")
    _enable_notifications(space)
    manager = make_member("emit-stocktake-manager", space)
    session = StocktakeSession.objects.create(
        makerspace=space,
        status=StocktakeSession.Status.COUNTING,
        started_at=timezone.now(),
    )
    with django_capture_on_commit_callbacks(execute=True):
        complete_stocktake(manager, session)
    assert Notification.objects.filter(
        makerspace=space, event="stocktake.completed"
    ).exists()


def test_emit_failure_does_not_break_workflow(monkeypatch, django_capture_on_commit_callbacks):
    space = make_space("emit-stocktake-safe")
    _enable_notifications(space)
    manager = make_member("emit-stocktake-safe-manager", space)
    session = StocktakeSession.objects.create(
        makerspace=space,
        status=StocktakeSession.Status.COUNTING,
        started_at=timezone.now(),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("db exploded")

    # Realistic failure mode: the notification row write itself fails. The helper
    # swallows it (and it runs post-commit anyway), so the workflow still completes.
    monkeypatch.setattr(Notification.objects, "create", boom)
    with django_capture_on_commit_callbacks(execute=True):
        result = complete_stocktake(manager, session)
    result.refresh_from_db()
    assert result.status == StocktakeSession.Status.COMPLETED
    assert not Notification.objects.filter(makerspace=space).exists()
